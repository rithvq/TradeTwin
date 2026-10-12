import base64
import hashlib
import json
import re
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .structured import compact_payload, lossless_json, parse


def decoded(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid compact encoding")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def verify(token, keys, environment, attachment_id):
    result = {
        "signature_integrity": "UNSUPPORTED",
        "issuer_trust": "UNKNOWN",
        "trusted_key_id": None,
        "covered_field_paths": [],
        "normalised_result": {},
        "limitations": [
            "Offline signature verification does not establish current IRN status, "
            "delivery, payment, or dispatch readiness."
        ],
    }
    try:
        header64, payload64, signature64 = token.split(".")
        header = lossless_json(decoded(header64))
        if not isinstance(header, dict):
            return result
        decoded(payload64)
        if header.get("alg") != "RS256" or header.get("crit") or header.get("b64") is False:
            return result
        kid = header.get("kid")
        candidates = [
            k
            for k in keys
            if k["key_identifier"] == kid
            and k["algorithm"] == "RS256"
            and k["key_purpose"] == "IRP_SIGNATURE"
            and k["status"] == "ACTIVE"
            and k["provider_environment"] == environment
        ]
        if not candidates:
            return {
                **result,
                "signature_integrity": "KEY_UNAVAILABLE",
                "limitations": result["limitations"]
                + ["No trusted key for this issuer, purpose, environment, and policy."],
            }
        key = candidates[0]
        instant = datetime.now(UTC)
        for field, operator in (
            ("effective_from", lambda a, b: a > b),
            ("effective_until", lambda a, b: a < b),
        ):
            if key.get(field) and operator(datetime.fromisoformat(key[field]), instant):
                return {**result, "signature_integrity": "KEY_UNAVAILABLE"}
        pem = key["public_key_reference"].encode()
        if hashlib.sha256(pem).hexdigest() != key["key_fingerprint"]:
            return {**result, "signature_integrity": "KEY_UNAVAILABLE", "issuer_trust": "UNTRUSTED"}
        public_key = serialization.load_pem_public_key(pem)
        if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
            return result
        # The signing input is the untouched compact token, never reconstructed JSON.
        public_key.verify(
            decoded(signature64),
            f"{header64}.{payload64}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        try:
            canonical, observations, _ = parse(
                json.dumps({"SignedInvoice": token}).encode(), attachment_id
            )
        except (ValueError, TypeError, KeyError):
            return {
                **result,
                "signature_integrity": "VALID",
                "issuer_trust": "TRUSTED_FOR_THIS_CHECK",
                "trusted_key_id": key["id"],
                "limitations": result["limitations"]
                + ["Signed business schema is unsupported; no captured fields are covered."],
            }
        payload = compact_payload(token)
        return {
            **result,
            "signature_integrity": "VALID",
            "issuer_trust": "TRUSTED_FOR_THIS_CHECK",
            "trusted_key_id": key["id"],
            "covered_field_paths": sorted({o["field_path"] for o in observations}),
            "normalised_result": {"signed_document": canonical, "payload_fields": sorted(payload)},
        }
    except InvalidSignature:
        return {
            **result,
            "signature_integrity": "INVALID",
            "issuer_trust": "TRUSTED_FOR_THIS_CHECK",
        }
    except (ValueError, TypeError, KeyError):
        return result
