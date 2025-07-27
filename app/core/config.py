"""Configuration management with Pydantic BaseSettings."""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # Application settings
    app_name: str = "OpenRouter Middleware"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8080
    reload: bool = False
    
    # Security settings
    session_secret_key: str = Field(..., min_length=32)
    admin_username: str = Field(..., min_length=3)
    admin_password: str = Field(..., min_length=8)
    
    # Redis settings
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_password: Optional[str] = None
    redis_max_connections: int = 20
    redis_retry_on_timeout: bool = True
    
    # OpenRouter settings
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_timeout: int = 30
    max_retries: int = 3
    
    # Rate limiting
    default_rate_limit: int = 1000  # requests per hour
    rate_limit_window: int = 3600  # seconds
    
    # CORS settings
    allowed_origins: List[str] = ["http://localhost:3000", "http://localhost:8080"]
    allowed_methods: List[str] = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allowed_headers: List[str] = ["*"]
    allow_credentials: bool = True
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    
    @validator("session_secret_key")
    def validate_session_secret_key(cls, v):
        if len(v) < 32:
            raise ValueError("Session secret key must be at least 32 characters long")
        return v
    
    @validator("admin_password")
    def validate_admin_password(cls, v):
        if len(v) < 8:
            raise ValueError("Admin password must be at least 8 characters long")
        return v
    
    @validator("redis_url")
    def validate_redis_url(cls, v):
        if not v.startswith(("redis://", "rediss://")):
            raise ValueError("Redis URL must start with redis:// or rediss://")
        return v
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        
        # Environment variable prefixes
        env_prefix = ""


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience function for accessing settings
settings = get_settings()