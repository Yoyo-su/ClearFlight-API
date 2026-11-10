from typing import Literal

from pydantic import ConfigDict, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration settings."""

    # API Keys
    AVIATIONSTACK_API_KEY: str
    WEATHERSTACK_API_KEY: str

    # Provider HTTP requests
    PROVIDER_TIMEOUT: float = 10.0  # seconds

    # Redis (REDIS_URL, e.g. an authenticated rediss:// URL, overrides host/port)
    REDIS_URL: str | None = None
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    CACHE_EXPIRE: int = 3600  # 1 hour

    # METAR observations (Aviation Weather Center)
    METAR_USER_AGENT: str = (
        "ClearFlight-API/0.1 (+https://github.com/Yoyo-su/ClearFlight-API)"
    )
    METAR_CACHE_TTL: int = 600  # seconds an observation is cached
    METAR_NO_DATA_CACHE_TTL: int = 300  # seconds a "no report" result is cached
    METAR_RATE_LIMIT_PER_MINUTE: int = 30  # provider requests per process
    METAR_CURRENT_MAX_MINUTES: int = 90  # older observations are stale
    METAR_STALE_MAX_MINUTES: int = 180  # older observations are expired

    # Live positions (CF-009 design r3; plan v1.1 §3, §8)
    POSITIONS_PROVIDER: Literal["adsblol", "opensky"] = "adsblol"  # C1
    POSITIONS_RADIUS_NM: float = 25.0  # C3
    POSITIONS_MAX_AGE_S: int = 60  # C4: older positions are never shown
    POSITIONS_CACHE_TTL: int = 30  # one query per airport per 30 s at most
    POSITIONS_DEADLINE_S: float = 20.0  # a whole fetch, incl. token and retry
    # Longer than the worst-case fetch: the deadline plus one socket read timeout
    POSITIONS_LOCK_LEASE_S: int = 40
    POSITIONS_COVERAGE_TTL: int = 86400  # C6: coverage evidence lasts 24 h
    ADSBLOL_RATE_LIMIT_PER_MINUTE: int = 30
    # OpenSky is for development/educational use only (P4); it runs only when
    # this is true. CF-006 checks it is false unless a written licence exists.
    OPENSKY_EDUCATIONAL_USE: bool = False
    OPENSKY_CLIENT_ID: SecretStr | None = None  # C2: both or neither
    OPENSKY_CLIENT_SECRET: SecretStr | None = None
    OPENSKY_DAILY_CREDIT_BUDGET: int | None = None  # default: 90% of the limit
    OPENSKY_TOKEN_URL: str = (
        "https://auth.opensky-network.org/auth/realms/opensky-network"
        "/protocol/openid-connect/token"
    )

    DEBUG: bool = False  # Enable for local debugging

    @field_validator(
        "OPENSKY_CLIENT_ID",
        "OPENSKY_CLIENT_SECRET",
        "OPENSKY_DAILY_CREDIT_BUDGET",
        mode="before",
    )
    @classmethod
    def empty_is_unset(cls, value):
        # Docker Compose passes unset variables as empty strings.
        return None if isinstance(value, str) and not value.strip() else value

    # App config
    model_config = ConfigDict(env_file=".env", extra="ignore")


settings = Settings()
