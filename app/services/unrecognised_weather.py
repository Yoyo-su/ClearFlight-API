import json
import logging

import redis

from app.services import cache
from app.services.metar import Observation

"""
Captures METAR weather groups the conditions index can't interpret, so they
can be reviewed and added to the scoring table later (D-007).

Each group is counted once per observation (not per request, since cached
observations are served many times). Counts and a last example are kept in
Redis without expiry; every group is also logged. Failures never affect the
response.
"""

logger = logging.getLogger(__name__)

COUNTS_KEY = "conditions:unrecognised_wx:counts"  # hash: group -> count
EXAMPLES_KEY = "conditions:unrecognised_wx:examples"  # hash: group -> JSON
SEEN_TTL = 2 * 24 * 3600  # seconds to remember an observation's groups as counted

# Marks the observation's group as counted and updates the count and example in
# one atomic step, so a failure can't leave a marker without its count.
RECORD_SCRIPT = """
if redis.call('SET', KEYS[1], 1, 'NX', 'EX', ARGV[1]) then
  redis.call('HINCRBY', KEYS[2], ARGV[2], 1)
  redis.call('HSET', KEYS[3], ARGV[2], ARGV[3])
  return 1
end
return 0
"""


def record(obs: Observation, groups: list[str]) -> None:
    """Log and count unrecognised weather groups from an observation."""
    for group in groups:
        logger.warning(
            "Unrecognised METAR weather group %r at %s (%s)",
            group,
            obs.station,
            obs.raw_text,
        )
        seen_key = (
            f"conditions:unrecognised_wx:seen:{obs.station}:"
            f"{obs.observed_at.isoformat()}:{group}"
        )
        example = {
            "station": obs.station,
            "observed_at": obs.observed_at.isoformat(),
            "raw_text": obs.raw_text,
        }
        try:
            cache.redis_client.eval(
                RECORD_SCRIPT,
                3,
                seen_key,
                COUNTS_KEY,
                EXAMPLES_KEY,
                SEEN_TTL,
                group,
                json.dumps(example),
            )
        except redis.RedisError as e:
            logger.warning("Couldn't record unrecognised weather group: %s", e)


def summary() -> list[dict]:
    """Recorded groups, most frequent first: [{group, count, example}]."""
    counts = cache.redis_client.hgetall(COUNTS_KEY)
    examples = cache.redis_client.hgetall(EXAMPLES_KEY)
    rows = [
        {
            "group": group,
            "count": int(count),
            "example": json.loads(examples[group]) if group in examples else None,
        }
        for group, count in counts.items()
    ]
    return sorted(rows, key=lambda row: (-row["count"], row["group"]))
