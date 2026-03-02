from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SR_", env_file=".env")

    # Server
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Security — shared secret for internal endpoints (proxy-gateway ↔ coordination-api)
    INTERNAL_API_SECRET: str = ""

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # Proxyjet.io — default/fallback proxy provider
    PROXYJET_HOST: str = ""
    PROXYJET_PORT: int = 8080
    PROXYJET_USERNAME: str = ""
    PROXYJET_PASSWORD: str = ""

    # Well-known IDs
    PROXYJET_NODE_ID: str = "00000000-0000-0000-0000-000000000001"


settings = Settings()
