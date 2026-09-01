import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["MINIO_ENABLED"] = "false"
os.environ["LOCAL_OBJECT_STORAGE_PATH"] = str(
    Path(tempfile.gettempdir()) / "tradetwin-document-service-tests"
)

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.main import SERVICE_NAME, app  # noqa: E402


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": SERVICE_NAME}
