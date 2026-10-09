from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "compliance-service"
    database_url: str = "sqlite+pysqlite:///./compliance_service.db"
    shipment_service_url: str = "http://shipment-service:8000"
    document_service_url: str = "http://document-service:8000"
    document_service_enabled: bool = True
    redis_url: str = "redis://redis:6379/0"
    redis_enabled: bool = True
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    auth_required: bool = False
    regulation_catalog_mode: Literal["demo", "reviewed"] = "demo"
    regulation_llm_base_url: str = "https://api.openai.com/v1"
    regulation_llm_model: str = "gpt-4o-mini"
    regulation_llm_api_key: str | None = None
    ors_api_key: str | None = None
    allow_external_routing: bool = False
    tradetwin_viewer_token: str | None = None
    tradetwin_operator_token: str | None = None
    tradetwin_admin_token: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
