# ruff: noqa: E402

import json
import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["REDIS_ENABLED"] = "false"

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.main import app


def test_compliance_http_contract_is_preserved():
    expected = json.loads((Path(__file__).parent / "fixtures/api-contract.json").read_text())
    actual = [
        {
            "path": path,
            "method": method,
            "operation_id": operation.get("operationId"),
            "responses": operation.get("responses"),
            "parameters": operation.get("parameters"),
            "request_body": operation.get("requestBody"),
            "tags": operation.get("tags"),
        }
        for path, operations in app.openapi()["paths"].items()
        for method, operation in operations.items()
    ]

    def key(item):
        return item["path"], item["method"]

    assert sorted(actual, key=key) == sorted(expected, key=key)
