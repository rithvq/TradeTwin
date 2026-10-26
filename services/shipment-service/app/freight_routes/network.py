"""Small allowlisted public-data clients; credential-bearing redirects are never followed."""

import json
from time import monotonic
from urllib.parse import urljoin, urlsplit

import httpx

from app.operations.access import fail


def document(
    client, method, url, *, hosts, headers=None, payload=None, params=None, limit=12_000_000
):
    deadline = monotonic() + 35
    for _ in range(4):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in hosts
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
        ):
            fail("ROUTE_SOURCE_NOT_APPROVED", "The route source endpoint is not approved.")
        try:
            with client.stream(
                method, url, headers=headers, json=payload, params=params
            ) as response:
                if response.is_redirect and not headers:
                    url = urljoin(url, response.headers["location"])
                    params = None
                    continue
                if response.status_code in {401, 403}:
                    fail(
                        "ROUTE_SOURCE_NOT_AUTHORISED",
                        "The route data provider did not authorize this request.",
                    )
                if response.status_code == 429:
                    fail(
                        "ROUTE_SOURCE_RATE_LIMITED",
                        "The route data provider rate limit was reached.",
                        status=503,
                    )
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if monotonic() > deadline:
                        fail("PROVIDER_UNAVAILABLE", "The route source exceeded its time limit.")
                    if len(content) > limit:
                        fail("ROUTE_SOURCE_INVALID", "The route source exceeded its size limit.")
                value = json.loads(content)
                return value
        except (httpx.HTTPError, ValueError, KeyError):
            fail(
                "PROVIDER_UNAVAILABLE",
                "The route data source is unavailable or invalid.",
                status=503,
            )
    fail("ROUTE_SOURCE_INVALID", "The route source redirected too many times.")
