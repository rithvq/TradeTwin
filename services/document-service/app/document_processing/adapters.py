"""Only explicit organisation connections may make read-only calls to approved providers."""

import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlsplit

import httpx

TYPES = {"GSTIN_AUTHORITY_LOOKUP", "IRN_LIVE_STATUS", "EWB_AUTHORITY_LOOKUP"}
PUBLIC_FIELDS = {
    "identifier",
    "status",
    "legal_name",
    "trade_name",
    "valid_from",
    "valid_until",
    "document_number",
    "document_date",
    "transporter_identifier",
    "vehicle_registration_number",
    "provider_observed_at",
    "request_reference",
    "supplier_gstin",
    "recipient_gstin",
    "invoice_value_minor",
    "transport_mode",
    "part_information",
}


class ReadOnlyAdapter:
    name, version = "AUTHORISED_READ_ONLY_V1", "1"

    def capabilities(self):
        return sorted(TYPES)

    def validateInput(self, kind, identifier):
        patterns = {
            "GSTIN_AUTHORITY_LOOKUP": r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]",
            "IRN_LIVE_STATUS": r"[a-fA-F0-9]{64}",
            "EWB_AUTHORITY_LOOKUP": r"\d{12}",
        }
        return (
            kind in patterns
            and isinstance(identifier, str)
            and bool(re.fullmatch(patterns[kind], identifier))
        )

    def describeLimitations(self):
        return [
            "A timestamped provider observation is not a universal authenticity "
            "or dispatch decision.",
            "Provider availability and requester restrictions depend on "
            "the organisation's authorised connection.",
        ]

    def normaliseResult(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("identifier"), str):
            raise ValueError("Provider returned an unsupported observation")
        return {
            k: v
            for k, v in payload.items()
            if k in PUBLIC_FIELDS and (v is None or isinstance(v, str))
        }

    def check(self, kind, identifier, connection, execution_mode):
        if not connection:
            return "NOT_CONFIGURED", {}, None
        if (
            kind not in connection["allowed_check_types_json"]
            or connection["status"] != "CONFIGURED"
        ):
            return "NOT_AUTHORISED", {}, None
        if execution_mode == "PRODUCTION" and connection["provider_environment"] != "LIVE":
            return "NOT_AUTHORISED", {}, None
        binding = os.getenv(f"DOCUMENT_PROVIDER_BINDING_{connection['secret_reference']}")
        if not binding:
            return "NOT_CONFIGURED", {}, None
        try:
            config = json.loads(binding)
            if config.get("organization_id") != connection.get("organization_id") or config.get(
                "provider_environment"
            ) != connection.get("provider_environment"):
                return "NOT_AUTHORISED", {}, None
            base = config["base_url"].rstrip("/")
            destination = urlsplit(base)
            allowlist = {
                h.strip().lower()
                for h in os.getenv("DOCUMENT_VERIFICATION_ALLOWED_HOSTS", "").split(",")
                if h.strip()
            }
            if (
                destination.scheme != "https"
                or destination.hostname not in allowlist
                or destination.username
                or destination.password
            ):
                return "NOT_AUTHORISED", {}, None
            addresses = socket.getaddrinfo(destination.hostname, destination.port or 443)
            if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                return "NOT_AUTHORISED", {}, None
            path = config.get("read_only_paths", {}).get(kind)
            if not path or not path.startswith("/") or path.startswith("//") or ".." in path:
                return "UNSUPPORTED", {}, None
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                response = client.get(
                    base + path,
                    params={
                        "identifier": identifier,
                        "requester_identifier": connection.get("requester_identifier"),
                    },
                    headers={"Authorization": f"Bearer {config['access_token']}"},
                )
            if response.status_code in {401, 403}:
                return "NOT_AUTHORISED", {}, None
            if response.status_code == 404:
                return "NOT_FOUND", {}, response.content
            if response.status_code >= 500:
                return "UNAVAILABLE", {}, response.content
            if response.status_code != 200 or len(response.content) > 1024 * 1024:
                return "ERROR", {}, None
            return "RESULT_RETURNED", self.normaliseResult(response.json()), response.content
        except httpx.TimeoutException:
            return "UNAVAILABLE", {}, None
        except httpx.HTTPError:
            return "UNAVAILABLE", {}, None
        except (ValueError, KeyError, OSError):
            return "ERROR", {}, None
