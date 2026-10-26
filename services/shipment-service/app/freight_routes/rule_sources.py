"""Byte-currency checks detect changed official sources, never interpret or publish new law."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx


def check(client, sources, live):
    def one(source):
        result = {key: source[key] for key in ("id", "title", "url", "recorded_at")}
        result["fingerprint_short"] = source["sha256"][:12]
        host = urlsplit(source["url"]).hostname or ""
        parsed = urlsplit(source["url"])
        if not live:
            return {**result, "status": "RETAINED_REFERENCE_NOT_LIVE_CHECKED"}
        if (
            parsed.scheme != "https"
            or not host.endswith((".gov.in", ".nic.in"))
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
        ):
            return {**result, "status": "NOT_APPROVED_FOR_LIVE_FETCH"}
        try:
            started, size, fingerprint = time.monotonic(), 0, hashlib.sha256()
            with client.stream(
                "GET", source["url"], headers={"Accept": "application/pdf,text/html"}
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 5_000_000 or time.monotonic() - started > 25:
                        raise ValueError("Source bound exceeded")
                    fingerprint.update(chunk)
            return {
                **result,
                "status": "CAPTURED_BYTES_UNCHANGED"
                if fingerprint.hexdigest() == source["sha256"]
                else "CHANGED_REVIEW_REQUIRED",
            }
        except (httpx.HTTPError, ValueError):
            return {**result, "status": "CURRENT_SOURCE_UNAVAILABLE"}

    with ThreadPoolExecutor(max_workers=3) as pool:
        checked = list(pool.map(one, sources[:6]))
    return checked + [
        {
            **{key: source[key] for key in ("id", "title", "url", "recorded_at")},
            "fingerprint_short": source["sha256"][:12],
            "status": "NOT_CHECKED_SOURCE_LIMIT",
        }
        for source in sources[6:]
    ]
