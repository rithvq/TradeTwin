import os

import httpx
from fastapi import HTTPException
from tradetwin_security import enabled, service_headers


def validate_shipment_links(shipment_id, consignment_id=None, event_id=None, cache=None):
    if not enabled():
        return
    cache = {} if cache is None else cache
    cached = cache.get(shipment_id)
    if cached is not None and (not event_id or "events" in cached):
        check_links(cached, consignment_id, event_id)
        return
    url = os.getenv("SHIPMENT_SERVICE_URL", "http://127.0.0.1:8011").rstrip("/")
    try:
        with httpx.Client(base_url=url, headers=service_headers(), timeout=10) as client:
            if shipment_id not in cache:
                response = client.get(f"/shipments/{shipment_id}")
                if response.status_code == 404:
                    raise HTTPException(status_code=404, detail="Shipment not found")
                response.raise_for_status()
                cache[shipment_id] = response.json()
            shipment = cache[shipment_id]
            if consignment_id and not any(
                c["id"] == consignment_id for c in shipment["consignments"]
            ):
                raise HTTPException(
                    status_code=422, detail="Consignment does not belong to shipment"
                )
            if event_id:
                if "events" not in shipment:
                    timeline = client.get(f"/shipments/{shipment_id}/timeline")
                    timeline.raise_for_status()
                    shipment["events"] = timeline.json()["events"]
                if not any(e["id"] == event_id for e in shipment["events"]):
                    raise HTTPException(status_code=422, detail="Event does not belong to shipment")
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503, detail="Shipment ownership could not be verified"
        ) from exc


def check_links(shipment, consignment_id, event_id):
    if consignment_id and not any(c["id"] == consignment_id for c in shipment["consignments"]):
        raise HTTPException(status_code=422, detail="Consignment does not belong to shipment")
    if event_id and not any(e["id"] == event_id for e in shipment["events"]):
        raise HTTPException(status_code=422, detail="Event does not belong to shipment")
