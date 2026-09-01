from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import settings


def get_shipment_context(shipment_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        with httpx.Client(base_url=settings.shipment_service_url, timeout=10) as client:
            shipment_response = client.get(f"/shipments/{shipment_id}")
            timeline_response = client.get(f"/shipments/{shipment_id}/timeline")
            shipment_response.raise_for_status()
            timeline_response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shipment not found",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Shipment service returned an error",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shipment service is unavailable",
        ) from exc

    return shipment_response.json(), timeline_response.json().get("events", [])


def list_shipments() -> list[dict[str, Any]]:
    try:
        response = httpx.get(f"{settings.shipment_service_url}/shipments", timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shipment service is unavailable",
        ) from exc

    return response.json()
