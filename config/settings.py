"""
Settings — configuración centralizada desde variables de entorno.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    # ─── OpenAI ──────────────────────────────────────────────────────────
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")

    # ─── Anthropic (fallback opcional) ───────────────────────────────────
    anthropic_api_key: str = Field("", env="ANTHROPIC_API_KEY")

    # ─── Chatwoot ────────────────────────────────────────────────────────
    chatwoot_base_url: str = Field(..., env="CHATWOOT_BASE_URL")
    chatwoot_api_token: str = Field(..., env="CHATWOOT_API_TOKEN")
    chatwoot_account_id: int = Field(1, env="CHATWOOT_ACCOUNT_ID")
    chatwoot_webhook_secret: str = Field("", env="CHATWOOT_WEBHOOK_SECRET")

    # ─── WhatsApp / Meta ─────────────────────────────────────────────────
    whatsapp_token: str = Field(..., env="WHATSAPP_TOKEN")
    whatsapp_phone_number_id: str = Field(..., env="WHATSAPP_PHONE_NUMBER_ID")

    # ─── Google Calendar ─────────────────────────────────────────────────
    google_credentials_json: str = Field(..., env="GOOGLE_CREDENTIALS_JSON")
    google_calendar_id: str = Field("primary", env="GOOGLE_CALENDAR_ID")

    # ─── Redis (opcional para memoria persistente) ────────────────────────
    redis_url: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    use_redis: bool = Field(False, env="USE_REDIS")

    # ─── PostgreSQL (multi-tenant) ────────────────────────────────────────
    database_url: str = Field("", env="DATABASE_URL")

    # ─── LLM Router ──────────────────────────────────────────────────────
    llm_tier1_model: str = Field("gpt-4o-mini", env="LLM_TIER1_MODEL")
    llm_tier2_model: str = Field("gpt-4o", env="LLM_TIER2_MODEL")
    llm_temperature: float = Field(0.3, env="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(1000, env="LLM_MAX_TOKENS")

    # ─── App ─────────────────────────────────────────────────────────────
    app_host: str = Field("0.0.0.0", env="APP_HOST")
    app_port: int = Field(8001, env="APP_PORT")
    debug: bool = Field(False, env="DEBUG")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    environment: str = Field("development", env="ENVIRONMENT")  # development | production
    test_token: str = Field("", env="TEST_TOKEN")  # Token para /test/message en desarrollo

    # ─── Security (FASE 2) ───────────────────────────────────────────────
    encryption_master_key: str = Field("", env="ENCRYPTION_MASTER_KEY")  # AES-256 key
    gdpr_token: str = Field("", env="GDPR_TOKEN")  # Token para /gdpr/delete-user

    # ─── Zona horaria ────────────────────────────────────────────────────
    timezone: str = Field("America/Bogota", env="TIMEZONE")

    class Config:
        env_file = "/opt/langgraph-assistant/.env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra fields from .env


@lru_cache()
def get_settings() -> Settings:
    return Settings()
