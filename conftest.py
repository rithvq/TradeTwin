"""Legacy unit scenarios use an isolated demo context; security tests enable auth explicitly."""

import base64
import os
import secrets

os.environ["PROFILE_AUTH_ENABLED"] = "false"
os.environ["DOCUMENT_ENCRYPTION_KEY"] = base64.b64encode(secrets.token_bytes(32)).decode()
