from pydantic_settings import BaseSettings
from pydantic import ConfigDict


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

    DEBUG: bool = False  # Enable for local debugging

    # App config
    model_config = ConfigDict(env_file=".env", extra="ignore")


settings = Settings()
