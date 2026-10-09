from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "document-service"
    database_url: str = "sqlite+pysqlite:///./document_service.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    minio_enabled: bool = True
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "tradetwin-local"
    minio_secret_key: str = "change-me-local-minio-password"
    minio_secure: bool = False
    minio_bucket: str = "tradetwin-documents"
    max_upload_bytes: int = 20 * 1024 * 1024
    document_encryption_key_file: Path = Path(".secrets/document-keyring.json")
    document_encryption_key: str | None = None
    local_object_storage_path: Path = Path(".local-object-store")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
