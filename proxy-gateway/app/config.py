from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SR_", env_file=".env")

    PROXY_PORT: int = 8080
    MANAGEMENT_PORT: int = 8081

    COORDINATION_API_URL: str = "http://localhost:8000"
    COORDINATION_API_SECRET: str = ""

    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    DEFAULT_RATE_LIMIT_RPM: int = 60
    NODE_REQUEST_TIMEOUT: float = 30.0
    AUTH_CACHE_TTL: int = 300
    BUFFER_SIZE: int = 65536

    LOG_LEVEL: str = "INFO"


settings = Settings()
