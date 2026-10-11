"""OpenAPI wire contracts derived from storage columns and the shared input validators."""

from copy import deepcopy

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Integer, Numeric, Uuid, inspect

from app.trades.models import Audit

from . import models
from .schemas import ConsignmentPlan


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def array(name):
    return {"type": "array", "items": ref(name)}


def object_schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def install(document):
    components = document["components"]["schemas"]
    string, boolean = {"type": "string"}, {"type": "boolean"}
    quantity = {"type": "string", "pattern": r"^-?\d+(?:\.\d{1,6})?$"}
    money = {"type": "string", "pattern": r"^\d+$", "description": "INR paise, never float"}
    mode = {"type": "string", "enum": ["PRODUCTION", "SIMULATION"]}
    names = (
        "Carrier",
        "Vehicle",
        "Consignment",
        "ConsignmentItem",
        "Assignment",
        "Event",
        "Receipt",
        "ReceiptLine",
        "Inspection",
        "Closure",
        "Reopening",
        "Dispute",
        "DisputeEvent",
        "Schedule",
        "ScheduleLine",
        "ScheduleApproval",
        "TriggerEvent",
        "Payment",
        "PaymentDecision",
        "PaymentAllocation",
        "Attachment",
        "Audit",
    )
    for name in names:
        properties, required = {}, []
        for column in inspect(Audit if name == "Audit" else getattr(models, name)).columns:
            if column.name in {"request_hash", "object_key"}:
                continue
            kind = column.type
            definition = (
                money
                if column.name.endswith("_minor")
                else (
                    {"type": "string", "format": "uuid"}
                    if isinstance(kind, Uuid)
                    else quantity
                    if isinstance(kind, Numeric)
                    else {"type": "string", "format": "date-time"}
                    if isinstance(kind, DateTime)
                    else {"type": "string", "format": "date"}
                    if isinstance(kind, Date)
                    else boolean
                    if isinstance(kind, Boolean)
                    else {"type": "integer"}
                    if isinstance(kind, Integer | BigInteger)
                    else {"type": "object", "description": f"Server snapshot: {column.name}"}
                    if isinstance(kind, JSON)
                    else string
                )
            )
            properties[column.name] = (
                {"anyOf": [definition, {"type": "null"}]} if column.nullable else definition
            )
            required.append(column.name)
        properties.update(
            execution_mode=mode, request_id={"type": "string", "format": "uuid"}, etag=string
        )
        components[f"Operational{name}"] = object_schema(properties, required)

    def extend(name, **properties):
        components[f"Operational{name}"]["properties"].update(properties)

    plan = ConsignmentPlan.model_json_schema(ref_template="#/components/schemas/{model}")
    components.update(plan.pop("$defs", {}))
    for field in ("items", "source_accepted_revision_id", "coordinating_organization_id"):
        plan["properties"].pop(field)
        plan["required"].remove(field)
    components["OperationalPlan"] = plan
    summary = object_schema(
        {
            **{
                k: quantity
                for k in (
                    "allocated_quantity",
                    "received_quantity",
                    "accepted_quantity",
                    "rejected_quantity",
                    "pending_inspection_quantity",
                    "awaiting_receipt_quantity",
                    "short_quantity",
                )
            },
            "loaded_quantity": {"anyOf": [quantity, {"type": "null"}]},
            "consignment_item_id": {"type": "string", "format": "uuid"},
            "line_ref": {"type": "string", "format": "uuid"},
            "description": string,
            "uqc": string,
            "inspection_status": string,
        }
    )
    components["OperationalQuantitySummary"] = summary
    extend(
        "Consignment",
        plan_json=ref("OperationalPlan"),
        items=array("OperationalConsignmentItem"),
        assignments=array("OperationalAssignment"),
        events=array("OperationalEvent"),
        documents=array("OperationalAttachment"),
        receipts=array("OperationalReceipt"),
        receipt_summary=array("OperationalQuantitySummary"),
        closures=array("OperationalClosure"),
        dispatch_readiness={"const": "NOT_ASSESSED"},
        allowed_actions={"type": "array", "items": string},
    )
    for field in ("pickup_address_snapshot", "delivery_address_snapshot"):
        components["OperationalConsignment"]["properties"][field] = ref("Address")
    components["OperationalAssignmentTask"] = deepcopy(components["OperationalAssignment"])
    components["OperationalAssignmentTask"]["properties"]["consignment"] = ref(
        "OperationalConsignment"
    )
    extend("Receipt", effective=boolean, head_etag=string, lines=array("OperationalReceiptLine"))
    extend(
        "ReceiptLine",
        accepted_quantity=quantity,
        rejected_quantity=quantity,
        pending_inspection_quantity=quantity,
        decisions=array("OperationalInspection"),
    )
    extend(
        "Event",
        recorded_at={"type": "string", "format": "date-time"},
        movement_status=string,
    )
    extend(
        "Closure",
        quantity_summary_json=object_schema(
            {"lines": array("OperationalQuantitySummary"), "execution_mode": mode}
        ),
    )
    extend(
        "Schedule",
        lines=array("OperationalScheduleLine"),
        approvals=array("OperationalScheduleApproval"),
    )
    extend(
        "Dispute",
        events=array("OperationalDisputeEvent"),
        allowed_actions={"type": "array", "items": string},
    )
    extend("Carrier", declaration_status={"const": "SELF_DECLARED"}, organization_name=string)
    extend("Vehicle", declaration_status={"const": "SELF_DECLARED"})
    extend(
        "Attachment",
        authenticity={"const": "NOT_ASSESSED"},
        scanner_note=string,
        upload=object_schema(
            {
                "method": {"const": "PUT"},
                "url": string,
                "multipart_field": {"const": "file"},
                "requires_organization_header": boolean,
            }
        ),
    )
    extend(
        "Payment",
        status=string,
        net_allocated_minor=money,
        unallocated_minor=money,
        decisions=array("OperationalPaymentDecision"),
        allocations=array("OperationalPaymentAllocation"),
        pending_void_request={"anyOf": [ref("OperationalPaymentDecision"), {"type": "null"}]},
        provider_verification={"const": "NOT_ASSESSED"},
        duplicate_reference_warning=boolean,
    )
    components["OperationalObligation"] = deepcopy(components["OperationalScheduleLine"])
    components["OperationalObligation"]["properties"].update(
        {
            "active_schedule_line_id": string,
            "trigger_met": boolean,
            "due_on": {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]},
            "net_allocated_minor": money,
            "remaining_minor": money,
            "overapplied_minor": money,
            "status": string,
        }
    )
    components["OperationalSettlement"] = object_schema(
        {
            **{
                k: money
                for k in (
                    "accepted_quoted_goods_total_minor",
                    "scheduled_goods_minor",
                    "reported_payment_minor",
                    "acknowledged_payment_minor",
                    "net_allocated_minor",
                    "unallocated_acknowledged_minor",
                    "outstanding_scheduled_minor",
                    "overapplied_minor",
                    "disputed_payment_minor",
                )
            },
            "trade_id": string,
            "execution_mode": mode,
            "request_id": string,
            "pricing_basis": string,
            "active_schedule_id": {"anyOf": [string, {"type": "null"}]},
            "schedule_status": string,
            "schedule_review_required": boolean,
            "obligations": array("OperationalObligation"),
            "payments": array("OperationalPayment"),
            "schedules": array("OperationalSchedule"),
            "trigger_history": array("OperationalTriggerEvent"),
            "provider_verification": {"const": "NOT_ASSESSED"},
            "final_invoice_reconciliation": {"const": "NOT_ASSESSED"},
            "allowed_actions": {"type": "array", "items": string},
        }
    )
    components["OperationalInspectionBatch"] = object_schema(
        {
            "execution_mode": mode,
            "request_id": string,
            "decisions": array("OperationalInspection"),
            "receipt_summary": array("OperationalQuantitySummary"),
        }
    )
    components["OperationalCandidate"] = object_schema(
        {
            "accepted_revision_id": string,
            "execution_mode": mode,
            "quoted_goods_total_minor": money,
            "pricing_basis": string,
            "status": {"type": "string", "enum": ["READY", "NEEDS_CLARIFICATION"]},
            "questions": {"type": "array", "items": string},
            "lines": {"type": "array", "items": ref("ScheduleLineInput")},
            "additional_tax_freight": {"const": "NOT_ASSESSED"},
            "final_invoice_reconciliation": {"const": "NOT_ASSESSED"},
        }
    )
    uuid = {"type": "string", "format": "uuid"}
    nullable_uuid = {"anyOf": [uuid, {"type": "null"}]}
    availability = object_schema(
        {
            "line_ref": uuid,
            "description": string,
            "uqc": string,
            **{
                k: quantity for k in ("ordered_quantity", "reserved_quantity", "available_quantity")
            },
        }
    )
    graph = object_schema(
        {
            "execution_mode": mode,
            "nodes": {
                "type": "array",
                "items": object_schema({"id": uuid, "type": string, "label": string}),
            },
            "edges": {
                "type": "array",
                "items": object_schema({"source": uuid, "target": uuid, "type": string}),
            },
        }
    )
    components["OperationalWorkspace"] = object_schema(
        {
            "trade_id": uuid,
            "execution_mode": mode,
            "agreement_status": string,
            "accepted_revision_id": nullable_uuid,
            "etag": string,
            "row_version": {"type": "integer"},
            "request_id": uuid,
            "availability": {"type": "array", "items": availability},
            "consignments": array("OperationalConsignment"),
            "disputes": array("OperationalDispute"),
            "settlement": {"anyOf": [ref("OperationalSettlement"), {"type": "null"}]},
            "exceptions": {
                "type": "array",
                "items": object_schema(
                    {
                        "type": string,
                        "consignment_id": uuid,
                        "source_id": uuid,
                        "fact_status": string,
                        "verification_status": string,
                        "execution_mode": mode,
                    }
                ),
            },
            "documents": array("OperationalAttachment"),
            "dispatch_readiness": {"const": "NOT_ASSESSED"},
            "allowed_actions": {"type": "array", "items": string},
            "graph": graph,
        }
    )
    components["OperationalPlanningContext"] = object_schema(
        {
            "schema_version": {"const": 1},
            "trade_id": uuid,
            "consignment_id": uuid,
            "execution_mode": mode,
            "accepted_revision_id": uuid,
            "source_accepted_revision_id": uuid,
            "consignment_row_version": {"type": "integer"},
            "revision_alignment": string,
            "origin_address": ref("Address"),
            "destination_address": ref("Address"),
            "origin_coordinates": {"type": "null"},
            "destination_coordinates": {"type": "null"},
            "pickup_window": object_schema(
                {
                    "start": {"type": "string", "format": "date-time"},
                    "end": {"type": "string", "format": "date-time"},
                }
            ),
            "delivery_deadline": {"type": "string", "format": "date-time"},
            "goods_lines": {
                "type": "array",
                "items": object_schema(
                    {
                        "line_ref": uuid,
                        "description": string,
                        "specification": {"anyOf": [string, {"type": "null"}]},
                        "allocated_quantity": quantity,
                        "uqc": string,
                        "cargo_constraints": {"type": "object"},
                        "declared_hsn": {"anyOf": [string, {"type": "null"}]},
                    }
                ),
            },
            "gross_weight_kg": quantity,
            "volume_m3": {"anyOf": [quantity, {"type": "null"}]},
            "package_count": {"type": "integer"},
            "commercial_freight_responsibility": string,
            "consolidation_allowed": boolean,
            "return_truck_allowed": boolean,
            "maximum_transshipments": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "assignment_reference": nullable_uuid,
            "movement_purpose": string,
            "dispatch_readiness": {"const": "NOT_ASSESSED"},
            "input_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "request_id": uuid,
        }
    )
    returns = {
        "vehicles": "Vehicle",
        "carrier-profile": "Carrier",
        "consignments": "Consignment",
        "preparations": "Consignment",
        "cancellations": "Consignment",
        "assignments": "Assignment",
        "decisions": "Assignment",
        "events": "Event",
        "receipts": "Receipt",
        "corrections": "Receipt",
        "reversals": "PaymentAllocation",
        "delivery-closures": "Closure",
        "reopenings": "Reopening",
        "disputes": "Dispute",
        "comments": "Dispute",
        "resolution-proposals": "Dispute",
        "resolution-decisions": "Dispute",
        "withdrawals": "Dispute",
        "payment-schedules": "Schedule",
        "approvals": "Schedule",
        "payments": "Payment",
        "acknowledgements": "Payment",
        "void-requests": "Payment",
        "void-decisions": "Payment",
        "allocations": "Payment",
        "uploads": "Attachment",
        "completions": "Attachment",
        "operations": "Workspace",
        "planning-context": "PlanningContext",
        "payment-schedule-candidate": "Candidate",
        "acceptances": "InspectionBatch",
    }
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            if "Trade operations - Phase 2" not in operation.get("tags", []):
                continue
            suffix = path.rsplit("/", 1)[-1]
            response_name = returns.get(suffix)
            if "/payments/" in path:
                response_name = "Payment"
            if path.startswith("/api/v1/inspection-decisions/"):
                response_name = "Inspection"
            if path == "/api/v1/consignments/{ident}":
                response_name = "Consignment"
            if path == "/api/v1/vehicles/{ident}":
                response_name = "Vehicle"
            if path == "/api/v1/assignments/{ident}":
                response_name = "AssignmentTask"
            if path == "/api/v1/operational-attachments/{ident}":
                response_name = "Attachment"
            if suffix == "settlement":
                response_name = "Settlement"
            response_schema = ref(f"Operational{response_name}") if response_name else None
            if method == "get" and suffix in {"vehicles", "events", "disputes"}:
                response_schema = object_schema(
                    {"items": array(f"Operational{returns[suffix]}"), "execution_mode": mode}
                )
            if method == "get" and suffix == "receipt-summary":
                response_schema = object_schema(
                    {
                        "lines": array("OperationalQuantitySummary"),
                        "execution_mode": mode,
                        "request_id": string,
                    }
                )
            if method == "get" and suffix in {"carriers", "transport-tasks"}:
                response_schema = object_schema(
                    {
                        "items": array(
                            "OperationalCarrier"
                            if suffix == "carriers"
                            else "OperationalAssignmentTask"
                        ),
                        "next_cursor": nullable_uuid,
                    }
                )
            if method == "get" and suffix == "drivers":
                response_schema = object_schema(
                    {
                        "items": {
                            "type": "array",
                            "items": object_schema({"id": uuid, "display_name": string}),
                        }
                    }
                )
            if method == "get" and suffix == "download":
                response_schema = object_schema(
                    {"url": string, "expires_at_epoch": {"type": "integer"}, "execution_mode": mode}
                )
            if path == "/api/v1/assignments/{ident}/evidence":
                response_schema = object_schema(
                    {
                        "assignment": ref("OperationalAssignment"),
                        "historical_evidence_only": {"const": True},
                        "execution_mode": mode,
                        "items": array("OperationalAudit"),
                    }
                )
            if path == "/api/v1/disputes/{ident}":
                response_schema = ref("OperationalDispute")
            if method == "get" and suffix == "carrier-profile":
                response_schema = {"anyOf": [ref("OperationalCarrier"), {"type": "null"}]}
            if response_schema:
                for status, response in operation["responses"].items():
                    if status.startswith("2"):
                        response.setdefault("content", {})["application/json"] = {
                            "schema": response_schema
                        }
