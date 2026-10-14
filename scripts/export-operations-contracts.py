"""Generate the authenticated Phase 2 vertical-slice collection and wire OpenAPI."""

import importlib.util
import json
from pathlib import Path

from contract_schema import scoped

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "commercial_contracts", ROOT / "scripts/export-commercial-contracts.py"
)
commercial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commercial)


def main():
    schema = scoped(
        commercial.app.openapi(), {"Commercial agreements", "Trade operations - Phase 2"}
    )
    variables = {
        "base_url": "http://localhost:8011",
        "trade_id": "",
        "accepted_revision_id": "",
        "line_ref": "",
        "pickup_start": "",
        "pickup_end": "",
        "delivery_at": "",
        "trade_etag": "",
        "schedule_id": "",
        "schedule_hash": "",
        "obligation_ref": "",
        "payment_id": "",
    }
    roles = {
        "seller_operations": "seller",
        "buyer_receiver": "buyer",
        "buyer_inspector": "buyer",
        "buyer_finance": "buyer",
        "seller_finance": "seller",
        "carrier_dispatcher": "carrier",
        "driver_one": "carrier",
        "driver_two": "carrier",
        "unrelated": "unrelated",
    }
    for role in roles:
        variables[f"{role}_token"] = ""
    for party in set(roles.values()):
        variables[f"{party}_organization_id"] = ""
    for index in (0, 1):
        for name in ("cn_id", "cn_etag", "item_id", "assignment_id", "vehicle_id", "driver_id"):
            variables[f"{name}_{index}"] = ""
    items = []

    def add(
        name, method, path, body=None, role="seller_operations", status=200, etag=None, script=()
    ):
        headers = [{"key": "X-Organization-Id", "value": "{{" + roles[role] + "_organization_id}}"}]
        request = {
            "method": method,
            "url": "{{base_url}}/api/v1" + path,
            "header": headers,
            "auth": {
                "type": "bearer",
                "bearer": [{"key": "token", "type": "string", "value": "{{" + role + "_token}}"}],
            },
        }
        if body is not None:
            headers.extend(
                [
                    {"key": "Content-Type", "value": "application/json"},
                    {"key": "Idempotency-Key", "value": "{{$guid}}"},
                ]
            )
            request["body"] = {
                "mode": "raw",
                "raw": json.dumps(body, indent=2),
                "options": {"raw": {"language": "json"}},
            }
        if etag:
            headers.append({"key": "If-Match", "value": "{{" + etag + "}}"})
        items.append(
            {
                "name": name,
                "request": request,
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                f"pm.test('HTTP {status}', "
                                f"() => pm.response.to.have.status({status}));",
                                "const r = pm.response.json(); const v = pm.collectionVariables;",
                                *script,
                            ],
                        },
                    }
                ],
            }
        )

    add(
        "Load confirmed SIMULATION agreement",
        "GET",
        "/trades/{{trade_id}}",
        script=[
            "v.set('accepted_revision_id', r.accepted_revision.id); "
            "v.set('line_ref', r.accepted_revision.facts.items[0].line_ref);",
            "const d=r.accepted_revision.facts.delivery_requirements; "
            "v.set('pickup_start',d.pickup_earliest_at);",
            "v.set('pickup_end',d.pickup_latest_at); v.set('delivery_at',d.delivery_deadline_at); "
            "v.set('trade_etag',r.etag);",
            "pm.test('SIMULATION only', () => pm.expect(r.execution_mode).to.eql('SIMULATION'));",
        ],
    )
    for index, quantity in enumerate(("40", "60")):
        cn = "{{cn_id_" + str(index) + "}}"
        body = {
            "source_accepted_revision_id": "{{accepted_revision_id}}",
            "coordinating_organization_id": "{{seller_organization_id}}",
            "planned_pickup_start": "{{pickup_start}}",
            "planned_pickup_end": "{{pickup_end}}",
            "expected_delivery_at": "{{delivery_at}}",
            "pickup_contact_name": "Demo seller",
            "pickup_contact_phone_e164": "+919876543210",
            "delivery_contact_name": "Demo buyer",
            "delivery_contact_phone_e164": "+919876543210",
            "declared_gross_weight_kg": "400",
            "package_type": "CARTON",
            "package_count": 4,
            "items": [{"line_ref": "{{line_ref}}", "allocated_quantity": quantity, "uqc": "NOS"}],
        }
        capture_cn = [
            f"v.set('cn_id_{index}',r.id); v.set('cn_etag_{index}',r.etag); "
            f"v.set('item_id_{index}',r.items[0].id);"
        ]
        add(
            f"Reserve {quantity} NOS",
            "POST",
            "/trades/{{trade_id}}/consignments",
            body,
            status=201,
            script=capture_cn,
        )
        add(
            f"Prepare {quantity} NOS",
            "POST",
            f"/consignments/{cn}/preparations",
            {},
            etag=f"cn_etag_{index}",
            script=capture_cn,
        )
        add(
            f"Propose carrier for {quantity} NOS",
            "POST",
            f"/consignments/{cn}/assignments",
            {
                "carrier_organization_id": "{{carrier_organization_id}}",
                "booking_start_at": "{{pickup_start}}",
                "booking_end_at": "{{delivery_at}}",
            },
            status=201,
            etag=f"cn_etag_{index}",
            script=[f"v.set('assignment_id_{index}',r.id);"],
        )
        assignment = "{{assignment_id_" + str(index) + "}}"
        add(
            f"Carrier explicitly accepts {quantity} NOS",
            "POST",
            f"/assignments/{assignment}/decisions",
            {
                "decision": "ACCEPT",
                "vehicle_id": "{{vehicle_id_" + str(index) + "}}",
                "driver_user_id": "{{driver_id_" + str(index) + "}}",
            },
            role="carrier_dispatcher",
        )
        for kind in ("PICKUP_CONFIRMED", "DEPARTED", "ARRIVED"):
            payload = (
                {
                    "items": [
                        {
                            "consignment_item_id": "{{item_id_" + str(index) + "}}",
                            "loaded_quantity": quantity,
                            "uqc": "NOS",
                        }
                    ],
                    "actual_gross_weight_kg": "400",
                    "actual_package_count": 4,
                }
                if kind == "PICKUP_CONFIRMED"
                else {}
            )
            add(
                f"Driver {index + 1}: {kind}",
                "POST",
                f"/consignments/{cn}/events",
                {
                    "client_event_id": "{{$guid}}",
                    "assignment_id": assignment,
                    "event_type": kind,
                    "occurred_at": "{{occurred_at}}",
                    "payload": payload,
                },
                role="driver_one" if index == 0 else "driver_two",
                status=201,
            )
        for receipt_index, received in enumerate(("20", "20") if index == 0 else ("60",)):
            add(
                f"Receive {received} NOS ({index}/{receipt_index})",
                "POST",
                f"/consignments/{cn}/receipts",
                {
                    "client_receipt_id": "{{$guid}}",
                    "received_at": "{{occurred_at}}",
                    "lines": [
                        {
                            "consignment_item_id": "{{item_id_" + str(index) + "}}",
                            "delivered_quantity": received,
                            "uqc": "NOS",
                            "observed_condition": "GOOD",
                        }
                    ],
                },
                role="buyer_receiver",
                status=201,
                script=["v.set('receipt_id',r.id); v.set('receipt_line_id',r.lines[0].id);"],
            )
            add(
                f"Inspect independently ({index}/{receipt_index})",
                "POST",
                "/receipts/{{receipt_id}}/acceptances",
                {
                    "decisions": [
                        {
                            "receipt_line_id": "{{receipt_line_id}}",
                            "accepted_quantity": received,
                            "rejected_quantity": "0",
                        }
                    ]
                },
                role="buyer_inspector",
                status=201,
            )
        add(
            f"Refresh consignment {index} ETag",
            "GET",
            f"/consignments/{cn}",
            role="buyer_receiver",
            script=capture_cn,
        )
        add(
            f"Close physical recording {index}",
            "POST",
            f"/consignments/{cn}/delivery-closures",
            {},
            role="buyer_receiver",
            status=201,
            etag=f"cn_etag_{index}",
        )
    add(
        "Critical failure: one extra NOS",
        "POST",
        "/trades/{{trade_id}}/consignments",
        {**body, "items": [{"line_ref": "{{line_ref}}", "allocated_quantity": "1", "uqc": "NOS"}]},
        status=409,
    )
    add(
        "Refresh agreement for schedule",
        "GET",
        "/trades/{{trade_id}}",
        role="buyer_finance",
        script=["v.set('trade_etag',r.etag);"],
    )
    add(
        "Propose goods-only schedule",
        "POST",
        "/trades/{{trade_id}}/payment-schedules",
        {
            "accepted_revision_id": "{{accepted_revision_id}}",
            "lines": [
                {
                    "label": "Goods on full delivery",
                    "face_amount_minor": "1000000",
                    "trigger": "FULL_DELIVERY",
                }
            ],
        },
        role="buyer_finance",
        etag="trade_etag",
        status=201,
        script=[
            "v.set('schedule_id',r.id); v.set('schedule_hash',r.content_hash); "
            "v.set('obligation_ref',r.lines[0].obligation_ref);"
        ],
    )
    for role in ("buyer_finance", "seller_finance"):
        add(
            f"{role}: approve same hash",
            "POST",
            "/payment-schedules/{{schedule_id}}/approvals",
            {"decision": "ACCEPT", "content_hash": "{{schedule_hash}}"},
            role=role,
        )
    add(
        "Report is not a bank acknowledgment",
        "POST",
        "/trades/{{trade_id}}/payments",
        {"amount_minor": "1000000", "paid_on": "{{paid_on}}", "method": "BANK_TRANSFER"},
        role="buyer_finance",
        status=201,
        script=[
            "v.set('payment_id',r.id); "
            "pm.test('Manual only',()=>pm.expect(r.status).to.eql('MANUAL_REPORTED'));"
        ],
    )
    batch = {"allocations": [{"obligation_ref": "{{obligation_ref}}", "amount_minor": "1000000"}]}
    add(
        "Critical failure: allocate unacknowledged",
        "POST",
        "/payments/{{payment_id}}/allocations",
        batch,
        role="seller_finance",
        status=409,
    )
    add(
        "Seller acknowledges report",
        "POST",
        "/payments/{{payment_id}}/acknowledgements",
        {},
        role="seller_finance",
    )
    add(
        "Allocate acknowledged paise",
        "POST",
        "/payments/{{payment_id}}/allocations",
        batch,
        role="seller_finance",
    )
    add(
        "Critical failure: buyer cannot acknowledge",
        "POST",
        "/payments/{{payment_id}}/acknowledgements",
        {},
        role="buyer_finance",
        status=403,
    )
    add(
        "Critical failure: unrelated trade read",
        "GET",
        "/trades/{{trade_id}}/operations",
        role="unrelated",
        status=404,
    )
    for path in ("settlement", "operations", "evidence-events"):
        add(f"Inspect final {path}", "GET", "/trades/{{trade_id}}/" + path, role="seller_finance")
    add("Versioned planning snapshot", "GET", "/consignments/{{cn_id_0}}/planning-context")
    collection = {
        "info": {
            "name": "TradeTwin Operational Phase 2",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": (
                "Seed a fresh SIMULATION namespace. Set actor session tokens/organization IDs "
                "and owned vehicle/driver IDs. No mock auth headers. Idempotency keys are fresh "
                "for new intent; preserve a key manually for retries. All additional tax/freight, "
                "dispatch and bank verification remain NOT_ASSESSED."
            ),
        },
        "variable": [{"key": key, "value": value} for key, value in variables.items()],
        "item": items,
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "pm.collectionVariables.set('occurred_at', new Date().toISOString());",
                        "pm.collectionVariables.set('paid_on', "
                        "new Date().toISOString().slice(0,10));",
                    ],
                },
            }
        ],
    }
    output = ROOT / "docs/postman"
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("operations-phase2.postman_collection.json", collection),
        ("operations-phase2.openapi.json", schema),
    ):
        (output / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(items)} role-scoped workflow/failure requests and current OpenAPI")


if __name__ == "__main__":
    main()
