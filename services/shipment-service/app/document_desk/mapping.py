from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from app.operations.access import exists, fail
from app.operations.models import Consignment, ConsignmentItem
from app.trades.models import Item, uid
from app.trades.terms import digest

from . import access
from .context import input_context, mapping_freshness
from .ledger import match, record, result, touch
from .models import FactRevision, LineMapping, MappingRevision, SubjectLink


def save(db, ctx, ident, payload):
    doc, trade = access.document(db, ctx, ident, "document.map", True)
    match(ctx, doc)
    if doc.canonical_document_id:
        fail(
            "DUPLICATE_CANONICAL_REVIEW_REQUIRED",
            "Map the canonical presentation only; aliases cannot allocate quantity.",
        )
    from .checks import duplicate_candidates

    if duplicate_candidates(db, ctx, doc):
        fail(
            "DUPLICATE_CANONICAL_REVIEW_REQUIRED",
            "Resolve accessible duplicate presentations before allocating this document.",
        )
    revision = exists(db, FactRevision, payload.fact_revision_id)
    if (
        revision.id != doc.effective_fact_revision_id
        or revision.document_version_id != doc.current_version_id
    ):
        fail(
            "REVIEW_HEAD_CHANGED", "Only the current submitted review can have effective mappings."
        )
    if str(payload.accepted_trade_revision_id) != trade.accepted_revision_id:
        fail("ASSESSMENT_INPUT_STALE", "Accepted commercial revision changed.")
    if (
        str(payload.base_mapping_revision_id) if payload.base_mapping_revision_id else None
    ) != doc.current_mapping_revision_id:
        fail("REVIEW_HEAD_CHANGED", "Mapping head changed.")
    lines = {line["document_line_ref"]: line for line in revision.canonical_document_json["lines"]}
    items = {
        i.line_ref: i
        for i in db.scalars(
            select(Item).where(Item.trade_revision_id == trade.accepted_revision_id)
        )
    }
    line_caps, target_caps, order_caps = (
        defaultdict(Decimal),
        defaultdict(Decimal),
        defaultdict(Decimal),
    )
    for m in payload.mappings:
        line = lines.get(str(m.document_line_ref))
        item = items.get(str(m.trade_line_ref))
        if not line or not item or line["quantity"] is None or not line["uqc"]:
            fail("REVIEW_HEAD_CHANGED", "Review quantity/UQC and select an accepted order line.")
        if m.uqc != line["uqc"] or m.uqc != item.uqc:
            fail("UQC_MISMATCH", "Mapping units must match exactly; conversion is not inferred.")
        line_caps[str(m.document_line_ref)] += m.mapped_quantity
        order_caps[str(m.trade_line_ref)] += m.mapped_quantity
        if line_caps[str(m.document_line_ref)] > Decimal(line["quantity"]):
            fail(
                "DOCUMENT_MAPPING_QUANTITY_EXCEEDED",
                "Mapping exceeds the reviewed document line quantity.",
            )
        if item.quantity is None or order_caps[item.line_ref] > item.quantity:
            fail(
                "DOCUMENT_MAPPING_QUANTITY_EXCEEDED",
                "Order-line and consignment portions cannot double-count ordered quantity.",
            )
        if m.target_kind == "CONSIGNMENT_ITEM":
            target = exists(db, ConsignmentItem, m.consignment_item_id)
            cn = exists(db, Consignment, target.consignment_id)
            if (
                cn.trade_id != trade.id
                or cn.planning_status == "CANCELLED"
                or target.line_ref != item.line_ref
            ):
                fail("NOT_FOUND", "Consignment mapping target not found.", status=404)
            if (
                cn.source_accepted_revision_id != trade.accepted_revision_id
                or cn.revision_alignment != "CURRENT"
            ):
                fail("ASSESSMENT_INPUT_STALE", "Consignment needs accepted-revision review first.")
            if target.uqc != m.uqc:
                fail("UQC_MISMATCH", "Consignment unit differs from the reviewed document.")
            access.consignment(db, ctx, cn.id)
            target_caps[target.id] += m.mapped_quantity
            if target_caps[target.id] > target.allocated_quantity:
                fail(
                    "CONSIGNMENT_MAPPING_QUANTITY_EXCEEDED",
                    "Mapping exceeds the consignment item allocation.",
                )
            if not db.scalar(
                select(SubjectLink).where(
                    SubjectLink.document_version_id == doc.current_version_id,
                    SubjectLink.subject_type == "CONSIGNMENT",
                    SubjectLink.subject_id == cn.id,
                    SubjectLink.revoked_at.is_(None),
                )
            ):
                db.add(
                    SubjectLink(
                        document_version_id=doc.current_version_id,
                        subject_type="CONSIGNMENT",
                        subject_id=cn.id,
                        created_by_user_id=ctx.user.id,
                    )
                )
                db.flush()
    context = input_context(db, doc)
    row = MappingRevision(
        id=uid(),
        document_id=doc.id,
        document_version_id=doc.current_version_id,
        fact_revision_id=revision.id,
        accepted_trade_revision_id=trade.accepted_revision_id,
        base_mapping_revision_id=doc.current_mapping_revision_id,
        source_context_json=context,
        content_hash=digest(payload.model_dump(mode="json")),
        created_by_user_id=ctx.user.id,
    )
    # Pin the new head before target queries can autoflush this immutable snapshot.
    context["mapping_revision_id"] = row.id
    row.source_context_json = context
    doc.current_mapping_revision_id = row.id
    db.add(row)
    db.flush()
    for m in payload.mappings:
        target = (
            db.get(ConsignmentItem, str(m.consignment_item_id)) if m.consignment_item_id else None
        )
        db.add(
            LineMapping(
                mapping_revision_id=row.id,
                document_line_ref=str(m.document_line_ref),
                trade_line_ref=str(m.trade_line_ref),
                target_kind=m.target_kind,
                consignment_item_id=str(m.consignment_item_id) if m.consignment_item_id else None,
                mapped_quantity=m.mapped_quantity,
                uqc=m.uqc,
                target_snapshot_json={
                    "consignment_id": target.consignment_id,
                    "allocated_quantity": str(target.allocated_quantity),
                    "uqc": target.uqc,
                }
                if target
                else {},
            )
        )
    touch(doc)
    record(
        db,
        ctx,
        "DOCUMENT_MAPPING_CONFIRMED",
        doc,
        detail={"mapping_revision_id": row.id, "content_hash": row.content_hash},
    )
    return {
        **result(row, doc),
        "etag": f'"{doc.row_version}"',
        "mappings": [m.model_dump(mode="json") for m in payload.mappings],
    }


def history(db, ctx, ident):
    doc, _ = access.document(db, ctx, ident)
    rows = []
    for row in db.scalars(
        select(MappingRevision)
        .where(MappingRevision.document_id == doc.id)
        .order_by(MappingRevision.created_at)
    ):
        rows.append(
            {
                **result(row, doc),
                "freshness": mapping_freshness(db, doc, row.source_context_json),
                "mappings": [
                    result(m, doc)
                    for m in db.scalars(
                        select(LineMapping).where(LineMapping.mapping_revision_id == row.id)
                    )
                ],
            }
        )
    return {"items": rows, "effective_mapping_id": doc.current_mapping_revision_id}


def suggestions(db, ctx, ident):
    doc, trade = access.document(db, ctx, ident)
    fact = (
        db.get(FactRevision, doc.effective_fact_revision_id)
        if doc.effective_fact_revision_id
        else None
    )
    items = (
        list(db.scalars(select(Item).where(Item.trade_revision_id == trade.accepted_revision_id)))
        if trade.accepted_revision_id
        else []
    )
    return {
        "suggestions": [
            {
                "document_line_ref": line["document_line_ref"],
                "trade_line_ref": i.line_ref,
                "suggested_quantity": line["quantity"],
                "uqc": i.uqc,
                "confidence": None,
                "limitation": "Description and unit equality is a suggestion, "
                "not a confirmed mapping.",
            }
            for line in (fact.canonical_document_json["lines"] if fact else [])
            for i in items
            if line["uqc"] == i.uqc
            and line["description"]
            and line["description"].casefold() == (i.description or "").casefold()
        ],
        "requires_human_confirmation": True,
    }
