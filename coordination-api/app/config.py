import logging
import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for the coordination API."""

    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    
    # SQLite config (local testing)
    USE_SQLITE: bool = True
    SQLITE_DB_PATH: str = "space_router.db"

    # Supabase config (production)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # Internal API authentication
    INTERNAL_API_SECRET: str = ""

    # ipinfo.io token for IP classification (optional — free tier works without)
    IPINFO_TOKEN: str = ""

    # Proxyjet fallback proxy (used when no residential nodes available)
    PROXYJET_HOST: str = ""
    PROXYJET_PORT: int = 8080
    PROXYJET_USERNAME: str = ""
    PROXYJET_PASSWORD: str = ""

    class Config:
        env_prefix = "SR_"
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()