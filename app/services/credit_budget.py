import secrets
import time
from datetime import datetime, timedelta, timezone

"""
Shared provider budgets and single-flight locks in Redis (plan v1.1 §3;
CF-009 design r3 §5).

Every operation runs as a Lua script, so it is atomic across processes. Redis
errors are raised, never treated as a miss: a provider with a hard quota is
then not called (fail closed).
"""

DAY_TTL_S = 48 * 3600

# KEYS: counter, day sentinel, per-second slot
# ARGV: cost, budget, day ttl
# Returns the new total, or -1 (counter lost), -2 (slot taken), -3 (over budget)
RESERVE = """
if redis.call('EXISTS', KEYS[3]) == 1 then return -2 end
local used = redis.call('GET', KEYS[1])
if not used then
  if redis.call('EXISTS', KEYS[2]) == 1 then return -1 end
  redis.call('SET', KEYS[1], 0, 'EX', ARGV[3])
  redis.call('SET', KEYS[2], 1, 'EX', ARGV[3])
  used = 0
end
used = tonumber(used)
if used + tonumber(ARGV[1]) > tonumber(ARGV[2]) then return -3 end
redis.call('SET', KEYS[3], 1, 'EX', 2)
return redis.call('INCRBY', KEYS[1], ARGV[1])
"""

# Raise the counter to at least ARGV[1]; never lower it or recreate a lost one.
RAISE = """
local used = redis.call('GET', KEYS[1])
if not used then return -1 end
if tonumber(used) < tonumber(ARGV[1]) then
  redis.call('SET', KEYS[1], ARGV[1], 'KEEPTTL')
  return tonumber(ARGV[1])
end
return tonumber(used)
"""

RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


class BudgetExhausted(Exception):
    """The daily budget is used up (or its counter was lost)."""

    def __init__(self, reason: str, retry_at: datetime):
        self.reason = reason  # "daily_budget"
        self.retry_at = retry_at
        super().__init__(reason)


class SlotBusy(Exception):
    """Another call already used this second's slot."""


def next_utc_midnight(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


class DailyBudget:
    """A per-UTC-day credit budget with a one-call-per-second slot."""

    def __init__(self, client, name: str, budget: int, clock=time.time):
        self.client = client
        self.name = name
        self.budget = budget
        self.clock = clock

    def keys(self, now: float) -> tuple[str, str, str]:
        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        base = f"budget:{self.name}"
        return f"{base}:{day}", f"{base}:started:{day}", f"{base}:slot:{int(now)}"

    def reserve(self, cost: int = 1) -> int:
        """Reserve `cost` credits before a call.

        Raises:
            BudgetExhausted: over budget, or the day's counter was lost.
            SlotBusy: this second's slot is taken; try again next second.
            redis.RedisError: Redis is unavailable (callers fail closed).
        """
        now = self.clock()
        result = self.client.eval(
            RESERVE, 3, *self.keys(now), cost, self.budget, DAY_TTL_S
        )
        if result == -2:
            raise SlotBusy()
        if result in (-1, -3):
            midnight = next_utc_midnight(datetime.fromtimestamp(now, timezone.utc))
            raise BudgetExhausted("daily_budget", midnight)
        return int(result)

    def raise_to(self, used: int) -> None:
        """Raise today's counter to at least `used` (provider's own count)."""
        counter, _, _ = self.keys(self.clock())
        self.client.eval(RAISE, 1, counter, int(used))

    def used(self) -> int | None:
        counter, _, _ = self.keys(self.clock())
        value = self.client.get(counter)
        return None if value is None else int(value)


class Lock:
    """A single-flight lease that only its owner can release."""

    def __init__(self, client, key: str, lease_s: int):
        self.client = client
        self.key = key
        self.lease_ms = int(lease_s * 1000)
        self.token = secrets.token_hex(16)

    def acquire(self) -> bool:
        return bool(self.client.set(self.key, self.token, nx=True, px=self.lease_ms))

    def release(self) -> None:
        self.client.eval(RELEASE, 1, self.key, self.token)
