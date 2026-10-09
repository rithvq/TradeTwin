"""Generate a local encryption key ring once. Never prints or replaces key material."""

import base64
import json
import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / ".secrets/document-keyring.json"
path.parent.mkdir(exist_ok=True, mode=0o700)
if path.exists():
    print("Document key ring already exists; left unchanged.")
else:
    payload = {
        "active": "document-v1",
        "keys": {"document-v1": base64.b64encode(secrets.token_bytes(32)).decode()},
    }
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        json.dump(payload, handle)
    print("Document key ring created. Back it up securely; never commit it.")
