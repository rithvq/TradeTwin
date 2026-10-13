"""Exact reviewed evidence binding and exclusive business-invoice reservation."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.document_desk.models import (
    Assessment,
    FactRevision,
    LineMapping,
    ManualAttestation,
    MappingRevision,
    VerificationCheck,
    VerificationResult,
)
from app.operations.access import exists, fail
from app.operations.models import ConsignmentItem
from app.trades.terms import digest

from . import context
from .facts import next_number, scoped_document
from .ledger import check_context, record
from .models import (
    Binding,
    Fact,
    Manifest,
    Reservation,
    ReservationEvent,
    TransportEvidence,
    Turnover,
)
from .turnover import fiscal_year, private_access


def document_ref(db, ctx, reference, trade_id):
    source, doc = scoped_document(db, ctx, reference["document_version_id"], trade_id, True)
    from .models import PrivateSource

    if (
        db.scalar(select(PrivateSource).where(PrivateSource.document_id == doc.id))
        or doc.document_type == "DRIVER_LICENCE"
    ):
        fail(
            "FORBIDDEN",
            "Private turnover and driver identity sources cannot enter "
            "shared movement-document bindings.",
            status=403,
        )
    fact = exists(db, FactRevision, reference["reviewed_fact_revision_id"])
    canonical = doc.canonical_document_id or doc.id
    if (
        reference["document_id"] != doc.id
        or reference["canonical_document_id"] != canonical
        or fact.id != doc.effective_fact_revision_id
        or fact.document_version_id != source.id
    ):
        fail(
            "REQUIRED_EVIDENCE_MISSING",
            "Pin this source's exact current submitted review and canonical identity.",
        )
    mapping = None
    if reference.get("mapping_revision_id"):
        mapping = exists(db, MappingRevision, reference["mapping_revision_id"])
        if (
            mapping.document_id != doc.id
            or mapping.id != doc.current_mapping_revision_id
            or mapping.fact_revision_id != fact.id
        ):
            fail(
                "EVALUATION_STALE",
                "Use this source's exact effective mapping revision.",
                status=412,
            )
        from app.document_desk.context import mapping_freshness

        if mapping_freshness(db, doc, mapping.source_context_json) != "CURRENT":
            fail(
                "EVALUATION_STALE",
                "Mapping targets changed; confirm a new exact mapping.",
                status=412,
            )
    return doc, fact, mapping


def coverage(db, cn, fact, mapping):
    if not mapping:
        return False
    goods = {
        i.id: i
        for i in db.scalars(select(ConsignmentItem).where(ConsignmentItem.consignment_id == cn.id))
    }
    lines = {line["document_line_ref"]: line for line in fact.canonical_document_json["lines"]}
    rows = list(
        db.scalars(select(LineMapping).where(LineMapping.mapping_revision_id == mapping.id))
    )
    sums, target_sums = {}, {}
    for row in rows:
        target = goods.get(row.consignment_item_id)
        line = lines.get(row.document_line_ref)
        if (
            not target
            or not line
            or row.target_kind != "CONSIGNMENT_ITEM"
            or row.trade_line_ref != target.line_ref
            or row.uqc != target.uqc
            or row.uqc != line.get("uqc")
        ):
            return False
        sums[row.document_line_ref] = (
            sums.get(row.document_line_ref, Decimal(0)) + row.mapped_quantity
        )
        target_sums[target.id] = target_sums.get(target.id, Decimal(0)) + row.mapped_quantity
    return (
        bool(lines)
        and set(sums) == set(lines)
        and set(target_sums) == set(goods)
        and all(
            line.get("quantity") is not None and sums[ident] == Decimal(line["quantity"])
            for ident, line in lines.items()
        )
        and all(target_sums[ident] == item.allocated_quantity for ident, item in goods.items())
    )


def reserve(db, ctx, trade, cn, doc, fact):
    canonical = fact.canonical_document_json
    header = canonical.get("header", {})
    issuer = canonical.get("parties", {}).get("supplier", {}) or {}
    if not header.get("document_number") or not header.get("issue_date") or not issuer.get("gstin"):
        return None
    key = digest(
        {
            "issuer_gstin": issuer["gstin"],
            "document_number": header["document_number"],
            "financial_year": fiscal_year(date.fromisoformat(header["issue_date"])),
        }
    )
    owner = context.inherited(db, trade, cn)["seller_organisation_id"]
    previous = db.scalar(
        select(Reservation)
        .where(
            Reservation.issuer_organisation_id == owner,
            Reservation.issuer_document_identity_hash == key,
            Reservation.released_at.is_(None),
        )
        .with_for_update()
    )
    if previous:
        if previous.consignment_id != cn.id:
            fail(
                "DOCUMENT_ALREADY_RESERVED",
                "This business invoice identity already supports another consignment.",
            )
        return previous
    row = Reservation(
        trade_id=trade.id,
        consignment_id=cn.id,
        issuer_organisation_id=owner,
        issuer_document_identity_hash=key,
        canonical_document_id=doc.canonical_document_id or doc.id,
        content_hash=key,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if (
            constraint == "uq_active_movement_invoice"
            or getattr(exc.orig, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_UNIQUE"
        ):
            fail(
                "DOCUMENT_ALREADY_RESERVED",
                "A concurrent preparation reserved this business invoice identity.",
            )
        raise
    db.add(
        ReservationEvent(
            reservation_id=row.id,
            event_type="RESERVED",
            reason="Exact complete movement-document basis",
            created_by_user_id=ctx.user.id,
        )
    )
    return row


def prepare(db, ctx, ident, payload):
    trade, cn, _ = context.access(db, ctx, ident, "compliance.evidence.link", True, True)
    check_context(ctx, context.version(db, trade.id), payload.expected_context_version)
    head = context.heads(db, cn, True)
    data = payload.bindings.model_dump(mode="json")
    facts = exists(db, Fact, data["compliance_fact_revision_id"])
    if (
        facts.consignment_id != cn.id
        or facts.id != head.current_fact_revision_id
        or facts.accepted_trade_revision_id != trade.accepted_revision_id
    ):
        fail(
            "EVALUATION_STALE",
            "Use this consignment's current independently reviewed facts.",
            status=412,
        )
    if not cn.active_assignment_id or facts.assignment_id != cn.active_assignment_id:
        fail("ASSIGNMENT_CHANGED", "Facts no longer describe the accepted assignment.")
    manifest = (
        exists(db, Manifest, data["loading_manifest_revision_id"])
        if data["loading_manifest_revision_id"]
        else None
    )
    if manifest and (
        manifest.consignment_id != cn.id
        or manifest.assignment_id != cn.active_assignment_id
        or manifest.id != head.current_loading_manifest_revision_id
    ):
        fail("LOADING_MANIFEST_MISMATCH", "Use the exact current prepared loading manifest.")
    if data["seller_turnover_declaration_id"]:
        declaration = exists(db, Turnover, data["seller_turnover_declaration_id"])
        private_access(db, ctx, declaration.seller_organisation_id, "turnover.read")
        if data["seller_turnover_declaration_id"] != facts.facts_json.get(
            "seller_turnover_declaration_id"
        ):
            fail(
                "REQUIRED_EVIDENCE_MISSING",
                "Turnover binding must match the reviewed declaration selection.",
            )
    from app.operations.access import aligned

    aligned(cn)
    refs = [data["movement_document"], *data["supporting_documents"]]
    checked = [document_ref(db, ctx, ref, trade.id) for ref in refs]
    doc, reviewed, mapping = checked[0]
    if doc.document_type != "TAX_INVOICE":
        fail(
            "UNSUPPORTED_SCOPE",
            "The first profile requires a complete issued tax invoice, not a purchase order.",
        )
    for _, _, selected_mapping in checked:
        if (
            selected_mapping
            and selected_mapping.accepted_trade_revision_id != trade.accepted_revision_id
        ):
            fail(
                "EVALUATION_STALE",
                "Document mapping describes an older commercial revision.",
                status=412,
            )
    source_ids = {ref["document_version_id"] for ref in refs}
    for result_id in data["verification_result_ids"]:
        result = exists(db, VerificationResult, result_id)
        check = exists(db, VerificationCheck, result.verification_check_id)
        if check.document_version_id not in source_ids:
            fail(
                "NOT_FOUND",
                "Verification result is outside the selected evidence sources.",
                status=404,
            )
    for attestation_id in data["manual_attestation_ids"]:
        attestation = exists(db, ManualAttestation, attestation_id)
        if attestation.document_version_id not in source_ids:
            fail("NOT_FOUND", "Manual observation is outside the selected sources.", status=404)
    for evidence_id in data["transport_evidence_revision_ids"]:
        evidence = exists(db, TransportEvidence, evidence_id)
        if evidence.consignment_id != cn.id or evidence.assignment_id != cn.active_assignment_id:
            fail("NOT_FOUND", "Transport evidence is outside this assignment.", status=404)
    for assessment_id in data["phase3_assessment_run_ids"]:
        assessment = exists(db, Assessment, assessment_id)
        if assessment.document_version_id not in source_ids:
            fail("NOT_FOUND", "Consistency assessment is outside the selected sources.", status=404)
    reservation = reserve(db, ctx, trade, cn, doc, reviewed)
    data.update(
        trade_id=trade.id,
        consignment_id=cn.id,
        assignment_id=cn.active_assignment_id,
        accepted_trade_revision_id=trade.accepted_revision_id,
        whole_invoice_coverage=coverage(db, cn, reviewed, mapping),
        reservation_id=reservation.id if reservation else None,
    )
    row = Binding(
        trade_id=trade.id,
        consignment_id=cn.id,
        assignment_id=cn.active_assignment_id,
        revision_number=next_number(db, Binding, cn),
        fact_revision_id=facts.id,
        turnover_declaration_id=data["seller_turnover_declaration_id"],
        loading_manifest_revision_id=manifest.id if manifest else None,
        binding_json=data,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    head.current_binding_revision_id = row.id
    head.row_version += 1
    record(db, ctx, "COMPLIANCE_BINDINGS_PREPARED", row)
    return {
        "id": row.id,
        "content_hash": row.content_hash,
        "whole_invoice_coverage": data["whole_invoice_coverage"],
        "context_version": context.version(db, trade.id),
    }


def release_reservations(db, ctx, cn):
    if cn.movement_status != "NOT_STARTED" or cn.planning_status != "CANCELLED":
        return
    from .clock import instant

    for reservation in db.scalars(
        select(Reservation)
        .where(Reservation.consignment_id == cn.id, Reservation.released_at.is_(None))
        .with_for_update()
    ):
        if reservation.first_consumed_movement_event_id:
            continue
        reservation.released_at = instant(db)
        db.add(
            ReservationEvent(
                reservation_id=reservation.id,
                event_type="RELEASED",
                reason="Valid pre-pickup cancellation",
                created_by_user_id=ctx.user.id,
            )
        )
