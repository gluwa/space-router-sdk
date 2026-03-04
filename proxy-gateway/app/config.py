"""Configuration for the proxy gateway."""

import logging
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for the proxy gateway."""

    # Ports
    PROXY_PORT: int = 8080
    MANAGEMENT_PORT: int = 8081

    # Coordination API
    COORDINATION_API_URL: str
    COORDINATION_API_SECRET: str

    # Optional Supabase direct access for request logging
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # Performance tuning
    DEFAULT_RATE_LIMIT_RPM: int = 60
    NODE_REQUEST_TIMEOUT: float = 30.0
    AUTH_CACHE_TTL: int = 300  # 5 minutes

    # Logging
    LOG_LEVEL: str = "INFO"
    
    # For SQLite testing (defaults to False in production)
    USE_SQLITE: bool = False

    class Config:
        env_prefix = "SR_"
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)