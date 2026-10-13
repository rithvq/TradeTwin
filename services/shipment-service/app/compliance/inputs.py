"""Produce typed predicates from exact reviewed source revisions, never quoted prices."""

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.document_desk.models import Document, FactRevision, VerificationCheck
from app.operations.models import Assignment, Event

from . import context, observations, privacy
from .models import Binding, Manifest, PrivateIdentity, Reservation, Turnover, TurnoverReview


def prepare(db, trade, cn, pack, action, at):
    inherited = context.inherited(db, trade, cn)
    head = context.heads(db, cn)
    binding = (
        db.get(Binding, head.current_binding_revision_id)
        if head and head.current_binding_revision_id
        else None
    )
    facts = (
        db.get(context.Fact, head.current_fact_revision_id)
        if head and head.current_fact_revision_id
        else None
    )
    editable = facts.facts_json if facts else {}
    result = {
        "inherited": inherited,
        "facts": editable,
        "invoice": {},
        "turnover": {},
        "proof": {},
        "diagnostics": {},
        "authority_deadlines": [],
        "action": action,
    }
    proof, deadlines, dimensions = result["proof"], [], []
    if not binding or not facts or binding.fact_revision_id != facts.id:
        return result, deadlines, dimensions
    result["binding"] = binding.binding_json
    assignment = db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    manifest = (
        db.get(Manifest, binding.loading_manifest_revision_id)
        if binding.loading_manifest_revision_id
        else None
    )
    ref = binding.binding_json["movement_document"]
    document = db.get(Document, ref["document_id"])
    reviewed = db.get(FactRevision, ref["reviewed_fact_revision_id"])
    invoice = reviewed.canonical_document_json
    result["invoice"] = {
        **invoice.get("header", {}),
        **invoice.get("totals", {}),
        "type": document.document_type,
    }
    proof["movement_invoice"] = (
        document.document_type == "TAX_INVOICE" and document.lifecycle_status == "ACTIVE"
    )
    proof["invoice_formalities"] = observations.invoice_formalities(invoice, inherited, at)
    proof["whole_invoice_coverage"] = binding.binding_json.get("whole_invoice_coverage")
    proof["loading_manifest"] = (
        manifest is not None
        and manifest.id == head.current_loading_manifest_revision_id
        and manifest.assignment_id == cn.active_assignment_id
        and manifest.accepted_trade_revision_id == trade.accepted_revision_id
    )
    if action == "DEPARTED" and manifest:
        pickup = db.scalar(
            select(Event)
            .where(Event.consignment_id == cn.id, Event.event_type == "PICKUP_CONFIRMED")
            .order_by(Event.occurred_at.desc(), Event.id.desc())
        )
        actual = pickup.payload_json if pickup else None
        proof["loading_manifest"] = observations.together(
            [proof["loading_manifest"], pickup_matches(manifest.manifest_json, actual)]
        )
        result["diagnostics"]["LOADING_MANIFEST"] = {
            "actual_pickup_event_id": pickup.id if pickup else None,
            "prepared_manifest_matches_actual_pickup": proof["loading_manifest"],
        }
    reservation_id = binding.binding_json.get("reservation_id")
    reservation = db.get(Reservation, reservation_id) if reservation_id else None
    proof["invoice_reservation"] = bool(
        reservation and reservation.consignment_id == cn.id and reservation.released_at is None
    )
    proof["carried_documents"] = (
        True  # Actual possession is separately required by the packet/ACK gate.
    )
    proof["einvoice_signature"] = observations.signature(
        db, binding, invoice, trade.execution_mode, at
    )
    from app.document_desk.models import TrustedKey, VerificationResult

    for ident in binding.binding_json.get("verification_result_ids", []):
        data = db.get(VerificationResult, ident).result_json
        key = db.get(TrustedKey, data["trusted_key_id"]) if data.get("trusted_key_id") else None
        if key and key.effective_until:
            deadlines.append(context.aware(key.effective_until))
    turnover = (
        # Private values are decrypted only below, never included in an exported snapshot.
        db.get(Turnover, binding.turnover_declaration_id)
        if binding.turnover_declaration_id
        else None
    )
    if turnover:
        basis_current = turnover.source_basis_manifest_json == [
            context.source_state(db, i) for i in turnover.source_document_version_ids
        ]
        review = db.scalar(
            select(TurnoverReview)
            .where(TurnoverReview.declaration_id == turnover.id)
            .order_by(TurnoverReview.created_at.desc(), TurnoverReview.id.desc())
        )
        if (
            review
            and review.decision == "APPROVE_DECLARATION"
            and turnover.assessment_invoice_date == result["invoice"].get("issue_date")
            and basis_current
        ):
            identity = db.get(PrivateIdentity, turnover.pan_identity_reference)
            raw = privacy.unseal(
                identity.encrypted_identity_json, turnover.seller_organisation_id, identity.id
            )
            gstin = inherited.get("seller_gstin")
            if gstin and raw["pan"] == gstin[2:12]:
                derived = privacy.unseal(
                    turnover.derived_context_json,
                    turnover.seller_organisation_id,
                    turnover.id + ":derived",
                )
                result["turnover"] = {
                    k: derived[k]
                    for k in (
                        "exceeds_five_crore",
                        "exclusion_resolved",
                        "irp_ten_crore_or_more",
                        "hsn_required_digits",
                    )
                }
    digits = result["turnover"].get("hsn_required_digits")
    hsn = [line.get("hsn_code") for line in invoice.get("lines", [])]
    proof["hsn_digits"] = (
        None
        if digits is None or not hsn or any(code is None for code in hsn)
        else all(len(code) >= digits for code in hsn)
    )
    policies = pack.policy_json.get("proof_policy", {})
    for name, gstin in [
        ("supplier", inherited.get("seller_gstin")),
        ("recipient", inherited.get("buyer_gstin")),
    ]:
        value, expiry, detail = observations.observation(
            db,
            binding,
            "GSTIN_AUTHORITY_LOOKUP",
            {"identifier": gstin},
            policies.get("GSTIN", {}),
            at,
            trade.execution_mode,
        )
        proof[name + "_gst_active"] = value
        dimensions += detail
        if expiry:
            deadlines.append(expiry)
    proof["authority_assurance"] = observations.together(
        [proof.get("supplier_gst_active"), proof.get("recipient_gst_active")]
    )
    irn = result["invoice"].get("irn")
    proof["einvoice_present"] = True if irn and len(irn) == 64 else None
    value, expiry, detail = observations.observation(
        db,
        binding,
        "IRN_LIVE_STATUS",
        {"identifier": irn},
        policies.get("IRN", {}),
        at,
        trade.execution_mode,
    )
    proof["irn_live"] = value
    dimensions += detail
    if expiry:
        deadlines.append(expiry)
    proof["einvoice_proof"] = observations.together(
        [proof["einvoice_present"], proof["einvoice_signature"], value]
    )
    issue, acknowledged = (
        result["invoice"].get("issue_date"),
        result["invoice"].get("acknowledgment_at"),
    )
    from zoneinfo import ZoneInfo

    acknowledged_at = observations.timestamp(acknowledged)
    proof["irp_reporting_window"] = (
        None
        if not issue or not acknowledged_at
        else 0
        <= (
            acknowledged_at.astimezone(ZoneInfo("Asia/Kolkata")).date() - date.fromisoformat(issue)
        ).days
        < 30
    )
    ewb_references = []
    for source in binding.binding_json.get("supporting_documents", []):
        doc = db.get(Document, source["document_id"])
        if doc.document_type == "EWAY_BILL_COPY":
            fact = db.get(FactRevision, source["reviewed_fact_revision_id"])
            ewb_references.append((source, fact.canonical_document_json))
    proof["ewb_present"] = bool(ewb_references)
    (
        proof["ewb_identity"],
        proof["ewb_validity"],
        proof["ewb_arrival_window"],
        proof["ewb_portal_controls"],
    ) = None, None, None, None
    if len(ewb_references) == 1 and assignment:
        source, canonical = ewb_references[0]
        ewb, packing = canonical.get("eway_bill", {}), canonical.get("packing_transport", {})
        expected = {
            "identifier": ewb.get("eway_bill_number"),
            "document_number": result["invoice"].get("document_number"),
            "document_date": result["invoice"].get("issue_date"),
            "vehicle_registration_number": assignment.vehicle_snapshot.get("registration_number"),
            "supplier_gstin": inherited.get("seller_gstin"),
            "recipient_gstin": inherited.get("buyer_gstin"),
            "invoice_value_minor": result["invoice"].get("grand_total_minor"),
            "transport_mode": "ROAD",
            "part_information": "FULL_COPY",
        }
        value, expiry, detail = observations.observation(
            db,
            binding,
            "EWB_AUTHORITY_LOOKUP",
            expected,
            policies.get("EWB", {}),
            at,
            trade.execution_mode,
        )
        dimensions += detail
        if expiry:
            deadlines.append(expiry)
        tests = [
            value,
            observations.same(
                ewb.get("referenced_document_number"), result["invoice"].get("document_number")
            ),
            observations.same(
                ewb.get("referenced_document_date"), result["invoice"].get("issue_date")
            ),
            observations.same(
                ewb.get("declared_invoice_value_minor"), result["invoice"].get("grand_total_minor")
            ),
            observations.same(
                ewb.get("vehicle_registration_number"), expected["vehicle_registration_number"]
            ),
            observations.same(ewb.get("part_information"), "FULL_COPY"),
            observations.same(packing.get("transport_mode_declared"), "ROAD"),
        ]
        proof["ewb_identity"] = observations.together(tests)
        result["diagnostics"]["EWB_IDENTITY"] = {
            "expected_vehicle": expected["vehicle_registration_number"],
            "observed_vehicle": ewb.get("vehicle_registration_number"),
            "expected_part_information": "FULL_COPY",
            "observed_part_information": ewb.get("part_information"),
            "identity_outcome": value,
        }
        start, end = (
            observations.timestamp(ewb.get("valid_from_at")),
            observations.timestamp(ewb.get("valid_until_at")),
        )
        # Authority expiry must agree with the reviewed record, never guessed from an old FAQ.
        authority_ends = [
            observations.timestamp(
                db.get(VerificationResult, ident)
                .result_json.get("normalised_result", {})
                .get("valid_until")
            )
            for ident in binding.binding_json.get("verification_result_ids", [])
            if db.get(
                VerificationCheck, db.get(VerificationResult, ident).verification_check_id
            ).check_type
            == "EWB_AUTHORITY_LOOKUP"
        ]
        proof["ewb_validity"] = observations.together(
            [
                value,
                None if not start or not end else start <= at < end,
                None if not end or not authority_ends else end in authority_ends,
            ]
        )
        arrival = observations.timestamp(editable.get("expected_arrival_at"))
        proof["ewb_arrival_window"] = None if not end or not arrival else arrival < end
        if end:
            deadlines.append(end)
            result["authority_deadlines"].append(
                {
                    "code": "EWB_AUTHORITY_EXPIRY",
                    "timestamp": end.isoformat(),
                    "requirement_code": "EWB_VALIDITY",
                    "document_version_id": source["document_version_id"],
                    "class": "LEGAL",
                    "meaning": "Bound EWB expiry; authority agreement is separately checked.",
                }
            )
        generated = observations.timestamp(ewb.get("generated_at"))
        proof["ewb_portal_controls"] = (
            None
            if not generated or not issue
            else 0
            <= (
                generated.astimezone(ZoneInfo("Asia/Kolkata")).date() - date.fromisoformat(issue)
            ).days
            <= 180
        )
        from datetime import timedelta

        proof["ewb_portal_controls"] = observations.together(
            [
                proof["ewb_portal_controls"],
                None if not generated or not end else end <= generated + timedelta(days=360),
            ]
        )
    if assignment:
        corridor = [
            inherited["origin_state_code"],
            *(editable.get("declared_transit_state_codes") or []),
            inherited["destination_state_code"],
        ]
        arrival = observations.timestamp(editable.get("expected_arrival_at"))
        value, expiry, detail = observations.transport(
            db, binding, assignment, corridor, at, arrival, inherited.get("insurance_required")
        )
        proof["transport_assurance"] = value
        dimensions += detail
        for record in detail:
            if record.get("valid_until"):
                result["authority_deadlines"].append(
                    {
                        "code": "TRANSPORT_EVIDENCE_EXPIRY",
                        "timestamp": record["valid_until"],
                        "requirement_code": "TRANSPORT_ASSURANCE",
                        "evidence_revision_id": record["evidence_revision_id"],
                        "class": "LEGAL",
                        "meaning": "Transport record expiry, not observation freshness.",
                    }
                )
        if expiry:
            deadlines.append(expiry)
    return result, deadlines, dimensions


def pickup_matches(prepared, actual):
    if not actual:
        return None
    try:

        def quantities(items):
            return {
                i["consignment_item_id"]: (Decimal(i["loaded_quantity"]), i["uqc"]) for i in items
            }

        return (
            len(actual["items"]) == len(quantities(actual["items"]))
            and quantities(prepared["items"]) == quantities(actual["items"])
            and Decimal(prepared["actual_prepared_gross_weight_kg"])
            == Decimal(actual["actual_gross_weight_kg"])
            and prepared["actual_prepared_package_count"] == actual["actual_package_count"]
        )
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None
