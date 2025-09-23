from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application configuration settings."""
    
    # API Keys
    AVIATIONSTACK_API_KEY: str
    WEATHERSTACK_API_KEY: str
    
    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    CACHE_EXPIRE: int = 3600  # 1 hour
    
    DEBUG: bool = False # Enable for local debugging
    
    class Config:
        env_file = ".env"  # auto-loads .env file

settings = Settings()