"""End-to-end domestic workflow assertions against an isolated service stack."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx


def exercise(services, token=None):
    with httpx.Client(
        timeout=60, headers={"Authorization": f"Bearer {token}"} if token else {}
    ) as client:

        def call(service, method, path, **kwargs):
            response = client.request(
                method, f"http://127.0.0.1:{services[service]}{path}", **kwargs
            )
            assert response.is_success, (service, path, response.status_code, response.text[:600])
            return response

        for service in services:
            call(service, "GET", "/health")
            if service != "api":
                call(service, "GET", "/ready")
        source = call("shipment", "POST", "/demo/seed").json()
        payload = {
            key: source[key]
            for key in (
                "shipment_reference",
                "exporter_country",
                "importer_country",
                "transport_mode",
                "planned_departure_at",
                "planned_arrival_at",
                "domestic",
                "route_legs",
                "consignments",
            )
        }
        payload["shipment_reference"] = "TT-DOMESTIC-CHECK-" + uuid.uuid4().hex[:8]
        shipment = call("shipment", "POST", "/shipments", json=payload).json()
        shipment_id = shipment["id"]
        base = f"/shipments/{shipment_id}"
        try:
            shirts = next(
                item for item in shipment["consignments"] if item["product_name"] == "Cotton shirts"
            )
            stationery = next(
                item for item in shipment["consignments"] if item["product_name"] == "Stationery"
            )
            now = datetime.now(UTC)
            for i, (kind, location, target) in enumerate(
                [
                    ("CREATED", shipment["domestic"]["origin"], None),
                    ("LOADED", shipment["domestic"]["origin"], None),
                    ("ARRIVED_AT_HUB", shipment["route_legs"][0]["domestic"]["destination"], None),
                    ("DELIVERED", stationery["domestic"]["destination"], stationery["id"]),
                ]
            ):
                call(
                    "shipment",
                    "POST",
                    base + "/events",
                    json={
                        "event_type": kind,
                        "location_country": "India",
                        "consignment_id": target,
                        "occurred_at": (now + timedelta(seconds=i)).isoformat(),
                        "metadata": {"location": location},
                    },
                )
            updated = call("shipment", "GET", base).json()
            assert updated["status"] == "PARTIALLY_DELIVERED"
            graph = call("shipment", "GET", base + "/graph").json()
            assert len([node for node in graph["nodes"] if node["type"] == "Location"]) == 3

            def upload(item, kind, body):
                document = call(
                    "document",
                    "POST",
                    base + "/documents",
                    data={
                        "document_type": kind,
                        "jurisdiction": "India",
                        "consignment_id": item["id"],
                    },
                    files={"file": (kind + ".txt", body.encode(), "text/plain")},
                ).json()
                return call("document", "POST", f"/documents/{document['id']}/extract").json()

            for item in shipment["consignments"]:
                document = upload(
                    item,
                    "tax_invoice",
                    f"Invoice Number: INV-{item['id'][:8]}\n"
                    f"Product Name: {item['product_name']}\nQuantity: {item['quantity']}\n"
                    f"Declared Value: INR {item['declared_value']}\nOrigin State: Tamil Nadu\n"
                    f"Destination State: {item['domestic']['destination']['state']}",
                )
                assert document["extracted_fields"]["origin_state"] == "Tamil Nadu"
            before = call("compliance", "POST", f"/compliance/evaluate/{shipment_id}").json()
            assert before["result"]["missing_documents"] == ["eway_bill"]
            statuses = {
                item["consignment_id"]: item["status"]
                for item in before["result"]["consignment_results"]
            }
            assert statuses[shirts["id"]] == "CONDITIONALLY_COMPLIANT"
            assert statuses[stationery["id"]] == "COMPLIANT"
            document = upload(
                shirts,
                "eway_bill",
                "E-way Bill Number: 123456789012\nProduct Name: Cotton shirts\nQuantity: 100",
            )
            assert document["extracted_fields"]["eway_bill_number"] == "123456789012"
            after = call("compliance", "POST", f"/compliance/evaluate/{shipment_id}").json()
            assert after["status"] == "COMPLIANT"
            evidence = call("document", "GET", f"/assessments/{after['id']}/evidence").json()
            assert any(record["document_id"] == document["id"] for record in evidence)
            routes = call("compliance", "POST", f"/optimizer/route-options/{shipment_id}").json()
            assert routes["recommended_route_id"] == "domestic-planned"
            assert all(
                option["estimated_duty"] == 0 and not option["fta_eligible"]
                for option in routes["options"]
            )
            risk = call("intelligence", "POST", f"/intelligence/risk-score/{shipment_id}").json()
            assert risk["model_version"] == "domestic-synthetic-v1"
            assert "includes_uae" not in risk["features"]
            rule = call("compliance", "POST", "/regulations").json()
            call("compliance", "POST", f"/regulations/{rule['id']}/publish-version")
            impact = call(
                "compliance",
                "POST",
                "/regulations/impact-analysis",
                json={"regulation_ids": [rule["id"]]},
            ).json()
            affected = next(
                item for item in impact["impacted_shipments"] if item["shipment_id"] == shipment_id
            )
            assert affected["previous_status"] == "COMPLIANT"
            assert affected["new_status"] == "CONDITIONALLY_COMPLIANT"
            report = call(
                "compliance", "GET", f"/reports/compliance/{shipment_id}?format=html"
            ).text
            assert "Chennai" in report and "Pune" in report
            assert call(
                "compliance", "GET", f"/reports/compliance/{shipment_id}?format=pdf"
            ).content.startswith(b"%PDF")
            call("compliance", "POST", f"/consistency/check/{shipment_id}")
            call("compliance", "GET", base + "/questions")
            print(
                "PASS: domestic creation, delivery, extraction, independent assessments, "
                "evidence, routes, risk, policy impact, reports"
            )
        finally:
            call("shipment", "DELETE", base)
