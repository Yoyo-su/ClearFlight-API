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

    DEBUG: bool = False  # Enable for local debugging

    # App config
    model_config = ConfigDict(env_file=".env", extra="ignore")


settings = Settings()
