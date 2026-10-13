"""PAN-level fiscal history, exact thresholds, independent review and private projections."""

from datetime import date

from sqlalchemy import select

from app.operations.access import exists, fail
from app.trades.access import require
from app.trades.models import Registration, uid
from app.trades.terms import digest

from . import privacy
from .ledger import independent, record
from .models import PrivateIdentity, Turnover, TurnoverReview

FIVE_CRORE = 5_000_000_000
TEN_CRORE = 10_000_000_000


def fiscal_year(day):
    return day.year if day.month >= 4 else day.year - 1


def derive(declaration):
    invoice_date = date.fromisoformat(declaration["assessment_invoice_date"])
    current = fiscal_year(invoice_date)
    expected = list(range(2017, current))
    rows = {
        r["financial_year_start"]: r
        for r in declaration["relevant_financial_years"]
        if r["financial_year_start"] < current
    }
    missing = [
        year
        for year in expected
        if year not in rows
        or rows[year]["existence_status"] == "UNKNOWN"
        or (
            rows[year]["existence_status"] == "IN_EXISTENCE"
            and rows[year].get("pan_aggregate_turnover_minor") is None
        )
    ]
    known = [
        int(r["pan_aggregate_turnover_minor"])
        for r in rows.values()
        if r["existence_status"] == "IN_EXISTENCE"
        and r.get("pan_aggregate_turnover_minor") is not None
    ]
    maximum = max(known) if known else None
    previous = rows.get(current - 1)
    last = (
        int(previous["pan_aggregate_turnover_minor"])
        if previous
        and previous["existence_status"] == "IN_EXISTENCE"
        and previous.get("pan_aggregate_turnover_minor") is not None
        else None
    )
    complete = declaration["history_completeness_declared"] and not missing
    exclusion = declaration["supplier_exclusion_code"]
    return {
        "relevant_years_expected": expected,
        "missing_years": missing,
        "maximum_known_preceding_turnover_minor": str(maximum) if maximum is not None else None,
        "immediately_preceding_fy_turnover_minor": str(last) if last is not None else None,
        "history_complete": complete,
        "exclusion_resolved": True if exclusion == "NONE_CLAIMED" else None,
        "exceeds_five_crore": True
        if maximum is not None and maximum > FIVE_CRORE
        else False
        if complete and maximum is not None and exclusion == "NONE_CLAIMED"
        else None,
        "irp_ten_crore_or_more": True
        if maximum is not None and maximum >= TEN_CRORE
        else False
        if complete and maximum is not None and exclusion == "NONE_CLAIMED"
        else None,
        "hsn_required_digits": 6
        if last is not None and last > FIVE_CRORE
        else 4
        if last is not None
        else None,
        "interpretation_timezone": "Asia/Kolkata",
        "assessment_invoice_date": invoice_date.isoformat(),
    }


def private_access(db, ctx, organisation_id, permission):
    if ctx.org_id != str(organisation_id):
        fail("NOT_FOUND", "Private declaration not found.", status=404)
    require(db, ctx.user, ctx.org_id, permission)


def identity(db, ctx, organisation_id, payload):
    private_access(db, ctx, organisation_id, "turnover.prepare")
    ident = uid()
    row = PrivateIdentity(
        id=ident,
        seller_organisation_id=ctx.org_id,
        created_by_user_id=ctx.user.id,
        encrypted_identity_json=privacy.seal({"pan": payload.pan}, ctx.org_id, ident),
        identity_hash=privacy.identity_hash(payload.pan),
    )
    db.add(row)
    record(db, ctx, "PRIVATE_PAN_IDENTITY_REGISTERED", row)
    return {"id": row.id, "identity_type": "PAN", "raw_identity": "REDACTED"}


def prepare(db, ctx, organisation_id, payload):
    from .context import source_state

    private_access(db, ctx, organisation_id, "turnover.prepare")
    reference = exists(db, PrivateIdentity, payload.pan_identity_reference)
    if reference.seller_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Private identity not found.", status=404)
    value = payload.model_dump(mode="json")
    if value["supplier_exclusion_code"] not in {"UNKNOWN", "NONE_CLAIMED"}:
        fail(
            "UNSUPPORTED_SCOPE",
            "No published supplier-exclusion predicate supports this code.",
            status=422,
        )
    from app.document_desk.access import version as document_access

    for year in value["relevant_financial_years"]:
        for ident in year["source_document_version_ids"]:
            document_access(db, ctx, ident)
    from .models import PrivateSource

    source_ids = set(value["exclusion_basis_document_version_ids"]) | {
        i for year in value["relevant_financial_years"] for i in year["source_document_version_ids"]
    }
    for source_id in sorted(source_ids):
        version, document, _ = document_access(db, ctx, source_id)
        if (
            document.owner_organization_id != ctx.org_id
            or document.visibility != "OWNER_ONLY"
            or version.id != document.current_version_id
            or not document.effective_fact_revision_id
        ):
            fail(
                "REQUIRED_EVIDENCE_MISSING",
                "Turnover basis requires a current reviewed seller-owned private source; "
                "do not share PAN/history sources.",
                status=422,
            )
        if not db.scalar(select(PrivateSource).where(PrivateSource.document_id == document.id)):
            db.add(
                PrivateSource(
                    document_id=document.id,
                    seller_organisation_id=ctx.org_id,
                    created_by_user_id=ctx.user.id,
                )
            )
    pan = privacy.unseal(reference.encrypted_identity_json, ctx.org_id, reference.id)["pan"]
    registrations = list(
        db.scalars(select(Registration).where(Registration.organization_id == ctx.org_id))
    )
    derived = derive(value)
    derived["gstin_pan_match"] = (
        "MATCH"
        if any(r.gstin and r.gstin[2:12] == pan for r in registrations)
        else "MISMATCH"
        if registrations
        else "UNKNOWN"
    )
    ident = uid()
    row = Turnover(
        id=ident,
        seller_organisation_id=ctx.org_id,
        pan_identity_reference=reference.id,
        assessment_invoice_date=value["assessment_invoice_date"],
        schema_version=1,
        created_by_user_id=ctx.user.id,
        declaration_json=privacy.seal(value, ctx.org_id, ident),
        source_document_version_ids=sorted(source_ids),
        source_basis_manifest_json=[source_state(db, i) for i in sorted(source_ids)],
        derived_context_json=privacy.seal(derived, ctx.org_id, ident + ":derived"),
        content_hash=digest({"declaration": value, "derived": derived}),
    )
    db.add(row)
    record(db, ctx, "PAN_TURNOVER_DECLARATION_PREPARED", row)
    return {"id": row.id, "content_hash": row.content_hash, "review_outcome": "UNREVIEWED"}


def last_review(db, ident):
    return db.scalar(
        select(TurnoverReview)
        .where(TurnoverReview.declaration_id == str(ident))
        .order_by(TurnoverReview.created_at.desc(), TurnoverReview.id.desc())
    )


def read(db, ctx, ident):
    row = exists(db, Turnover, ident)
    private_access(db, ctx, row.seller_organisation_id, "turnover.read")
    value = privacy.unseal(row.declaration_json, ctx.org_id, row.id)
    derived = privacy.unseal(row.derived_context_json, ctx.org_id, row.id + ":derived")
    review = last_review(db, row.id)
    return {
        "id": row.id,
        "declaration": value,
        "derived": derived,
        "content_hash": row.content_hash,
        "review_outcome": "APPROVED_DECLARATION"
        if review and review.decision == "APPROVE_DECLARATION"
        else "RETURNED"
        if review
        else "UNREVIEWED",
    }


def review(db, ctx, ident, payload):
    from app.trades.context_locks import bump_context, registry_lock

    from .context import source_state
    from .models import Binding

    registry_lock(db, True)
    row = exists(db, Turnover, ident)
    private_access(db, ctx, row.seller_organisation_id, "turnover.review")
    independent(ctx, row.created_by_user_id)
    if payload.decision == "APPROVE_DECLARATION" and row.source_basis_manifest_json != [
        source_state(db, i) for i in row.source_document_version_ids
    ]:
        fail("EVALUATION_STALE", "Private basis changed; prepare a new declaration.", status=412)
    decision = TurnoverReview(
        declaration_id=row.id,
        decision=payload.decision,
        reason=payload.reason,
        created_by_user_id=ctx.user.id,
    )
    db.add(decision)
    record(db, ctx, "PAN_TURNOVER_DECLARATION_REVIEWED", decision)
    for trade_id in sorted(
        set(db.scalars(select(Binding.trade_id).where(Binding.turnover_declaration_id == row.id)))
    ):
        bump_context(db, trade_id, "PAN_TURNOVER_DECLARATION_REVIEWED")
    return {"id": decision.id, "declaration_id": row.id, "decision": decision.decision}


def conclusions(db, row):
    review = last_review(db, row.id) if row else None
    if not row or not review or review.decision != "APPROVE_DECLARATION":
        return {
            "reviewed": False,
            "exceeds_five_crore": None,
            "hsn_required_digits": None,
            "irp_ten_crore_or_more": None,
            "exclusion_resolved": None,
        }
    values = privacy.unseal(
        row.derived_context_json, row.seller_organisation_id, row.id + ":derived"
    )
    return {
        key: values[key]
        for key in (
            "exceeds_five_crore",
            "hsn_required_digits",
            "irp_ten_crore_or_more",
            "exclusion_resolved",
            "gstin_pan_match",
            "assessment_invoice_date",
        )
    } | {"reviewed": True}
