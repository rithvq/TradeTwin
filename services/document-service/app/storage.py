from io import BytesIO
from time import sleep
from uuid import uuid4

from fastapi import UploadFile
from minio import Minio

from app.config import settings


class ObjectStorage:
    def __init__(self) -> None:
        self.bucket = settings.minio_bucket
        self.client: Minio | None = None
        if settings.minio_enabled:
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )

    def ensure_bucket(self) -> None:
        if self.client is None:
            settings.local_object_storage_path.mkdir(parents=True, exist_ok=True)
            return

        last_error: Exception | None = None
        for _ in range(20):
            try:
                if not self.client.bucket_exists(self.bucket):
                    self.client.make_bucket(self.bucket)
                return
            except Exception as exc:
                last_error = exc
                sleep(1)
        if last_error is not None:
            raise last_error

    async def put_upload(
        self,
        shipment_id: str,
        document_id: str,
        upload: UploadFile,
    ) -> tuple[str, int]:
        filename = sanitize_filename(upload.filename or "document.bin")
        object_key = f"shipments/{shipment_id}/{document_id}-{filename}"
        content = await upload.read()

        if self.client is None:
            destination = settings.local_object_storage_path / object_key
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            return object_key, len(content)

        self.client.put_object(
            self.bucket,
            object_key,
            BytesIO(content),
            length=len(content),
            content_type=upload.content_type or "application/octet-stream",
        )
        return object_key, len(content)

    def get_bytes(self, object_key: str) -> bytes:
        if self.client is None:
            return (settings.local_object_storage_path / object_key).read_bytes()

        response = self.client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


def sanitize_filename(filename: str) -> str:
    keep = [character for character in filename if character.isalnum() or character in "._-"]
    cleaned = "".join(keep).strip("._")
    return cleaned or f"document-{uuid4().hex}.bin"
