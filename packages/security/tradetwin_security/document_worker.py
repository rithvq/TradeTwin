"""Narrow worker-to-storage authentication; never a browser or user session credential."""

import os
from pathlib import Path


def token():
    value = os.getenv("DOCUMENT_WORKER_TOKEN", "")
    path = os.getenv("DOCUMENT_WORKER_TOKEN_FILE")
    if not value and path:
        value = Path(path).read_text(encoding="ascii").strip()
    return value


def headers():
    value = token()
    if not value:
        raise RuntimeError("Document worker authentication is not configured")
    return {"X-Document-Worker-Token": value}
