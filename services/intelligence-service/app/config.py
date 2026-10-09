from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "intelligence-service"
    database_url: str = "sqlite+pysqlite:///./intelligence_service.db"
    shipment_service_url: str = "http://shipment-service:8000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    llm_provider: str = "mock"
    allow_private_data_llm: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    hs_confidence_threshold: float = 0.72

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
