"""Capability/licensing boundary for optional integrations; no permissive route fallback."""

import os

import httpx

from app.operations.access import fail

HOSTS = {"ORS_HGV": "api.openrouteservice.org"}


def capability(connection, mode, through):
    capabilities, licence = connection.capabilities_json, connection.licensing_json
    if connection.environment != mode:
        fail("MODE_MISMATCH", "Routing connection and trade environments must match.")
    if (
        connection.status != "CONFIGURED"
        or connection.vault_secret_reference != "env:ORS_API_KEY"
        or not os.getenv("ORS_API_KEY")
    ):
        fail(
            "PROVIDER_NOT_CONFIGURED",
            "An approved server-side routing connection and credential are required.",
        )
    if (
        connection.provider_code not in HOSTS
        or HOSTS[connection.provider_code] not in connection.approved_hosts_json
    ):
        fail("PROVIDER_NOT_CONFIGURED", "Provider host is not approved by server policy.")
    if (
        "IN" not in capabilities.get("supported_countries", [])
        or "ROAD_HGV" not in capabilities.get("supported_vehicle_modes", [])
        or capabilities.get("india_truck_coverage") != "APPROVED"
        or not capabilities.get("coverage_review_reference")
    ):
        fail(
            "TRUCK_ROUTING_UNSUPPORTED",
            "India truck-routing coverage has not been explicitly approved.",
        )
    if (
        not licence.get("derived_result_storage_allowed")
        or licence.get("retention_policy") == "NO_CONTENT_STORAGE"
    ):
        fail(
            "SOURCE_RETENTION_UNSUPPORTED",
            "Required operational results cannot lawfully be retained.",
        )
    if licence.get("retention_policy") == "UNTIL_DATE":
        from .routing import aware_from

        if not licence.get("retention_until") or through >= aware_from(licence["retention_until"]):
            fail(
                "SOURCE_RETENTION_UNSUPPORTED",
                "Routing licence does not cover intended operational use.",
            )


def minimal_request(pickup, drop, profile, cargo, departure):
    required = [
        "overall_height_mm",
        "overall_width_mm",
        "overall_length_mm",
        "combined_tare_weight_kg",
        "maximum_actual_axle_load_kg",
    ]
    if any(profile.get(k) is None for k in required):
        fail(
            "ROUTING_INPUT_MISSING",
            "Exact required truck measurements must be supplied, not permissive defaults.",
        )
    from decimal import Decimal

    return {
        "coordinates": [
            [str(pickup.longitude), str(pickup.latitude)],
            [str(drop.longitude), str(drop.latitude)],
        ],
        "departure_at": departure.isoformat(),
        "vehicle": {k: profile[k] for k in required},
        "loaded_weight_kg": str(
            Decimal(profile["combined_tare_weight_kg"]) + Decimal(cargo["gross_weight_kg"])
        ),
        "cargo_profile_codes": profile["supported_cargo_profile_codes"],
    }


def restriction_outcome(notices, fully_assessed):
    if any(n.get("critical") or n.get("violated") for n in notices):
        return "FAIL"
    return "PASS" if fully_assessed is True else "UNKNOWN"


def unavailable(exc):
    if isinstance(exc, httpx.HTTPError):
        fail(
            "PROVIDER_UNAVAILABLE",
            "Routing provider is unavailable; no synthetic or straight-line substitute was used.",
            status=503,
        )
    raise exc
