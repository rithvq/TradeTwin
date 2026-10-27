"""Locate bundled demo assets in both source checkouts and packaged containers."""

import os
from pathlib import Path

from app.operations.access import fail


def invoice():
    configured = os.getenv("DOCUMENT_FIXTURE_DIRECTORY")
    folders = (
        [Path(configured)]
        if configured
        else [parent / "data/fixtures/document-desk" for parent in Path(__file__).resolve().parents]
    )
    try:
        for folder in folders:
            source = folder / "invoice.pdf"
            if source.is_file():
                return source.read_bytes()
    except OSError:
        pass
    fail(
        "DEMO_FIXTURE_UNAVAILABLE",
        "The bundled demo invoice is unavailable. Repair the demo image or fixture directory.",
        status=503,
    )
