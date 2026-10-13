"""Generate a local encryption key ring once. Never prints or replaces key material."""

import base64
import csv
import json
import os
import secrets
import subprocess
from pathlib import Path


def restrict_windows_file(file_path):
    if os.name != "nt":
        return
    # POSIX creation modes do not reliably grant the owner access on Windows.
    identity = subprocess.check_output(["whoami.exe", "/user", "/fo", "csv", "/nh"], text=True)
    sid = next(csv.reader(identity.splitlines()))[1]
    subprocess.run(
        [
            "icacls.exe",
            str(file_path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:F",
            "*S-1-5-18:F",
            "*S-1-5-32-544:F",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


path = Path(__file__).resolve().parents[1] / ".secrets/document-keyring.json"
path.parent.mkdir(exist_ok=True, mode=0o700)
worker_path = path.parent / "document-worker-token"
if not worker_path.exists():
    with os.fdopen(
        os.open(worker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as handle:
        handle.write(secrets.token_urlsafe(48))
    print("Document worker credential created; never commit it.")
restrict_windows_file(worker_path)
if path.exists():
    print("Document key ring already exists; left unchanged.")
else:
    payload = {
        "active": "document-v1",
        "keys": {"document-v1": base64.b64encode(secrets.token_bytes(32)).decode()},
    }
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        json.dump(payload, handle)
    restrict_windows_file(path)
    print("Document key ring created. Back it up securely; never commit it.")
