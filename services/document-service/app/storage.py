import re
from io import BytesIO
from pathlib import PurePosixPath
from time import sleep
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from minio import Minio
from tradetwin_security import owner_id

from app.config import settings
from app.encryption import MAGIC, EncryptionError, seal, unseal


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
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", shipment_id):
            raise HTTPException(status_code=422, detail="Invalid shipment identifier")
        filename = sanitize_filename(upload.filename or "document.bin")
        if not filename.lower().endswith((".pdf", ".txt")):
            raise HTTPException(status_code=415, detail="Upload a PDF or plain text document")
        object_key = f"profiles/{owner_id()}/shipments/{shipment_id}/{document_id}.enc"
        content = await upload.read(settings.max_upload_bytes + 1)
        if not content:
            raise HTTPException(status_code=422, detail="Document is empty")
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Document exceeds the upload size limit")

        self.put_bytes(object_key, seal(content, f"document-object|{object_key}"))
        return object_key, len(content)

    def put_bytes(self, object_key: str, content: bytes) -> None:
        validate_object_key(object_key)
        if self.client is None:
            destination = settings.local_object_storage_path / object_key
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + f".{uuid4().hex}.tmp")
            temporary.write_bytes(content)
            temporary.replace(destination)
            return

        self.client.put_object(
            self.bucket,
            object_key,
            BytesIO(content),
            length=len(content),
            content_type="application/octet-stream",
        )

    def stored_bytes(self, object_key: str) -> bytes:
        validate_object_key(object_key)
        if self.client is None:
            return (settings.local_object_storage_path / object_key).read_bytes()

        response = self.client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_bytes(self, object_key: str) -> bytes:
        if not object_key.startswith(f"profiles/{owner_id()}/"):
            raise EncryptionError("Document does not belong to the current profile")
        return unseal(self.stored_bytes(object_key), f"document-object|{object_key}")

    def encrypt_existing(self, object_key: str) -> None:
        content = self.stored_bytes(object_key)
        context = f"document-object|{object_key}"
        if content.startswith(MAGIC):
            unseal(content, context)
        else:
            self.put_bytes(object_key, seal(content, context))


def sanitize_filename(filename: str) -> str:
    keep = [character for character in filename if character.isalnum() or character in "._-"]
    cleaned = "".join(keep).strip("._")
    return cleaned or f"document-{uuid4().hex}.bin"


def validate_object_key(object_key: str) -> None:
    if (
        not object_key
        or "\\" in object_key
        or ":" in object_key
        or PurePosixPath(object_key).is_absolute()
        or ".." in PurePosixPath(object_key).parts
    ):
        raise EncryptionError("Invalid document storage identifier")
