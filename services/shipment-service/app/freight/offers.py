"""RFQ grants and frozen carrier offers; submission never books resources."""

from sqlalchemy import select

from app.compliance.clock import aware, instant
from app.compliance.ledger import independent
from app.operations.access import aligned, before_pickup, exists, fail, match
from app.operations.ledger import record, touch, view
from app.operations.models import Carrier, Vehicle
from app.trades.access import require
from app.trades.models import User, uid
from app.trades.terms import digest

from .access import base_context, payer, planning, rfq_access
from .calculator import quote_totals
from .models import (
    RFQ,
    AssumptionReview,
    Assumptions,
    Invitation,
    Profile,
    Quote,
    QuoteEvent,
    QuoteHead,
    Template,
)
from .routing import latest_number


def operational(base, cn, templates):
    return {
        "pickup": cn.pickup_address_snapshot,
        "drop": cn.delivery_address_snapshot,
        "cargo": base["cargo_snapshot"],
        "route_templates": [
            {"id": t.id, "hash": t.content_hash, **t.template_json} for t in templates
        ],
        "execution_mode": base["execution_mode"],
    }


def create_rfq(db, ctx, ident, payload):
    trade, cn = planning(db, ctx, ident, "freight.rfq.prepare", True)
    match(ctx, cn)
    before_pickup(cn)
    aligned(cn)
    if ctx.org_id != cn.coordinating_organization_id:
        fail("FORBIDDEN", "The coordinating organisation prepares operational RFQs.", status=403)
    base = base_context(db, trade, cn)
    if (str(payload.pickup_location_revision_id), str(payload.drop_location_revision_id)) != (
        base["pickup_location_revision_id"],
        base["drop_location_revision_id"],
    ):
        fail("ROUTING_INPUT_MISSING", "Confirm current pickup/drop coordinates first.")
    templates = [exists(db, Template, i) for i in payload.requested_route_template_revision_ids]
    if any(t.consignment_id != cn.id for t in templates):
        fail("NOT_FOUND", "Route template not found.", status=404)
    if instant(db) >= payload.response_deadline:
        fail("RFQ_CONTEXT_STALE", "Response deadline must be in the future.")
    if payload.supersedes_rfq_id:
        old = exists(db, RFQ, payload.supersedes_rfq_id)
        if old.consignment_id != cn.id:
            fail("NOT_FOUND", "Predecessor RFQ not found.", status=404)
    data = {
        **payload.model_dump(mode="json"),
        "schema_version": 1,
        "accepted_trade_revision_id": trade.accepted_revision_id,
        "cargo_hash": base["cargo_hash"],
        "coordinating_organisation_id": cn.coordinating_organization_id,
        "operational_projection": operational(base, cn, templates),
    }
    row = RFQ(
        trade_id=trade.id,
        consignment_id=cn.id,
        requesting_organisation_id=ctx.org_id,
        freight_payer_organisation_id=base["freight_payer_organisation_id"],
        accepted_trade_revision_id=trade.accepted_revision_id,
        request_json=data,
        context_hash=base["planning_context_hash"],
        content_hash=digest(data),
        execution_mode=trade.execution_mode,
        response_deadline=payload.response_deadline,
        supersedes_rfq_id=str(payload.supersedes_rfq_id) if payload.supersedes_rfq_id else None,
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    for ident in set(payload.invited_carrier_organisation_ids):
        carrier = db.scalar(
            select(Carrier).where(Carrier.organization_id == str(ident), Carrier.active.is_(True))
        )
        if not carrier or carrier.profile_json["directory_visibility"] != "TRADING_PROFILE":
            fail("VALIDATION_ERROR", "Select active directory-listed carriers.", status=422)
        db.add(Invitation(rfq_id=row.id, carrier_organisation_id=str(ident)))
    record(db, ctx, "FREIGHT_RFQ_PREPARED", row, trade, cn)
    return view(row)


def publish(db, ctx, ident, payload):
    row, trade, cn, _ = rfq_access(db, ctx, ident, "freight.rfq.publish", True)
    match(ctx, row)
    if ctx.org_id != cn.coordinating_organization_id or row.lifecycle_projection != "DRAFT":
        fail("FORBIDDEN", "Only the coordinator can publish a draft RFQ.", status=403)
    if payload.content_hash != row.content_hash:
        fail("APPROVAL_HASH_MISMATCH", "RFQ hash changed.")
    if base_context(db, trade, cn)["planning_context_hash"] != row.context_hash or instant(
        db
    ) >= aware(row.response_deadline):
        fail("RFQ_CONTEXT_STALE", "Current routing/commercial context no longer matches this RFQ.")
    row.lifecycle_projection = "OPEN"
    touch(row)
    record(db, ctx, "FREIGHT_RFQ_PUBLISHED", row, trade, cn)
    return view(row)


def close(db, ctx, ident, payload):
    row, trade, cn, _ = rfq_access(db, ctx, ident, "freight.rfq.publish", True)
    match(ctx, row)
    if ctx.org_id != cn.coordinating_organization_id:
        fail("FORBIDDEN", "Only the coordinator closes an RFQ.", status=403)
    row.lifecycle_projection = "CLOSED"
    touch(row)
    record(db, ctx, "FREIGHT_RFQ_CLOSED", row, trade, cn)
    return view(row)


def invite(db, ctx, ident, payload):
    row, trade, cn, _ = rfq_access(db, ctx, ident, "freight.rfq.publish", True)
    match(ctx, row)
    if ctx.org_id != cn.coordinating_organization_id or row.lifecycle_projection not in {
        "DRAFT",
        "OPEN",
    }:
        fail("FORBIDDEN", "Only the coordinator can invite carriers to a current RFQ.", status=403)
    active = list(
        db.scalars(
            select(Invitation).where(Invitation.rfq_id == row.id, Invitation.revoked_at.is_(None))
        )
    )
    ids = set(str(i) for i in payload.carrier_organisation_ids) - {
        i.carrier_organisation_id for i in active
    }
    if len(active) + len(ids) > 30:
        fail("VALIDATION_ERROR", "At most 30 active invitations are supported.", status=422)
    for ident in ids:
        if not db.scalar(
            select(Carrier.id).where(Carrier.organization_id == ident, Carrier.active.is_(True))
        ):
            fail("RESOURCE_UNAVAILABLE", "Invited carrier is not active.")
        db.add(Invitation(rfq_id=row.id, carrier_organisation_id=ident))
    touch(row)
    record(db, ctx, "FREIGHT_RFQ_INVITATIONS_ADDED", row, trade, cn)
    return view(row)


def create_quote(db, ctx, ident, payload):
    rfq, trade, cn, invited = rfq_access(db, ctx, ident, lock=True)
    if not invited:
        fail("FORBIDDEN", "Only invited offering carriers prepare their own offers.", status=403)
    require(db, ctx.user, ctx.org_id, "freight.quote.prepare", trade.id)
    before_pickup(cn)
    base = base_context(db, trade, cn)
    if (
        rfq.lifecycle_projection != "OPEN"
        or base["planning_context_hash"] != rfq.context_hash
        or instant(db) >= aware(rfq.response_deadline)
    ):
        fail("RFQ_CONTEXT_STALE", "RFQ is closed, expired or based on changed inputs.")
    route = exists(db, Template, payload.route_template_revision_id)
    if route.id not in rfq.request_json["requested_route_template_revision_ids"]:
        fail("NOT_FOUND", "Requested route not found.", status=404)
    vehicle = exists(db, Vehicle, payload.vehicle_id)
    driver = exists(db, User, payload.driver_user_id)
    carrier = db.scalar(
        select(Carrier).where(Carrier.organization_id == ctx.org_id, Carrier.active.is_(True))
    )
    profile = exists(db, Profile, payload.routing_vehicle_profile_revision_id)
    if (
        not carrier
        or vehicle.carrier_organization_id != ctx.org_id
        or not vehicle.active
        or not driver.active
        or profile.vehicle_id != vehicle.id
        or profile.id != vehicle.current_routing_profile_revision_id
    ):
        fail(
            "RESOURCE_UNAVAILABLE",
            "Select current active owned vehicle/profile and carrier driver.",
        )
    if vehicle.execution_mode != trade.execution_mode:
        fail("MODE_MISMATCH", "Simulation and production resources cannot be mixed.")
    if require(db, driver, ctx.org_id, "shipment.event.record", trade.id).capability != "DRIVER":
        fail("RESOURCE_UNAVAILABLE", "Nominated user must have an active driver grant.")
    if {c.category_code for c in payload.service_coverage} != set(
        rfq.request_json["service_requirement_codes"]
    ):
        fail(
            "VALIDATION_ERROR",
            "Declare coverage exactly once per requested cost category.",
            status=422,
        )
    if payload.source_mode == "SIMULATION" and trade.execution_mode != "SIMULATION":
        fail("MODE_MISMATCH", "Fixture quotes cannot be production offers.")
    if payload.source_mode == "REVIEWED_QUOTE_DOCUMENT":
        from app.document_desk import access as docs

        version, doc, _ = docs.version(db, ctx, payload.quote_document_version_id)
        if (
            doc.owner_organization_id != ctx.org_id
            or doc.document_type != "FREIGHT_QUOTE"
            or doc.current_version_id != version.id
            or doc.effective_fact_revision_id != str(payload.quote_document_fact_revision_id)
        ):
            fail(
                "QUOTE_CONTEXT_STALE",
                "Offer adoption requires the carrier's exact current effective document review.",
            )
    from app.compliance.models import TransportEvidence

    for ident in payload.transport_evidence_revision_ids:
        ev = exists(db, TransportEvidence, ident)
        if (
            ev.owner_organisation_id != ctx.org_id
            or ev.consignment_id != cn.id
            or ev.subject_id not in {vehicle.id, driver.id}
        ):
            fail("NOT_FOUND", "Owned transport evidence not found.", status=404)
    head = (
        exists(db, QuoteHead, payload.quote_head_id)
        if payload.quote_head_id
        else QuoteHead(
            id=uid(), rfq_id=rfq.id, carrier_organisation_id=ctx.org_id, created_by=ctx.user.id
        )
    )
    if payload.quote_head_id:
        match(ctx, head)
        if (
            head.rfq_id != rfq.id
            or head.carrier_organisation_id != ctx.org_id
            or head.lifecycle_projection == "ACCEPTED"
        ):
            fail("QUOTE_CONTEXT_STALE", "Offer head is not available for revision.")
    else:
        db.add(head)
        db.flush()
    data = {
        **payload.model_dump(mode="json"),
        "schema_version": 1,
        "execution_mode": trade.execution_mode,
        "accepted_trade_revision_id": trade.accepted_revision_id,
        "source_context_hash": rfq.context_hash,
        "cargo_hash": base["cargo_hash"],
        "route_template_hash": route.content_hash,
        "vehicle_snapshot": vehicle.vehicle_json,
        "driver_assignment_snapshot": {"id": driver.id, "display_name": driver.display_name},
        "carrier_organisation_id": ctx.org_id,
    }
    net, tax, payable = quote_totals(data)
    data["carrier_payable_total_minor"] = str(payable) if payable is not None else None
    row = Quote(
        quote_head_id=head.id,
        revision_number=latest_number(db, Quote, Quote.quote_head_id == head.id),
        prior_revision_id=head.current_revision_id,
        route_template_revision_id=route.id,
        vehicle_id=vehicle.id,
        driver_user_id=driver.id,
        profile_revision_id=profile.id,
        source_context_hash=rfq.context_hash,
        valid_from=payload.valid_from,
        accept_by=payload.accept_by,
        carrier_net_minor=net,
        carrier_charged_tax_minor=tax,
        carrier_payable_total_minor=payable,
        quote_json=data,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "FREIGHT_QUOTE_DRAFTED", row, trade, cn)
    return {**view(row), "head_etag": f'"{head.row_version}"'}


def quote_event(db, ctx, ident, payload, action):
    quote = exists(db, Quote, ident)
    head = exists(db, QuoteHead, quote.quote_head_id)
    rfq, trade, cn, invited = rfq_access(db, ctx, head.rfq_id, lock=True)
    db.refresh(head)
    if not invited or head.carrier_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Carrier offer not found.", status=404)
    require(db, ctx.user, ctx.org_id, "freight.quote.submit", trade.id)
    match(ctx, head)
    if payload.content_hash != quote.content_hash:
        fail("APPROVAL_HASH_MISMATCH", "Offer decision requires the exact quote hash.")
    if head.lifecycle_projection == "ACCEPTED":
        fail(
            "COMMITMENT_CANCELLATION_REQUIRED",
            "Accepted offer is contract evidence; use bilateral cancellation.",
        )
    if action == "SUBMITTED":
        if (
            rfq.lifecycle_projection != "OPEN"
            or instant(db) >= aware(rfq.response_deadline)
            or quote.source_context_hash != base_context(db, trade, cn)["planning_context_hash"]
        ):
            fail("RFQ_CONTEXT_STALE", "RFQ no longer accepts this offer.")
        if (
            quote.quote_json["offer_kind"] == "FIRM_OFFER"
            and quote.carrier_payable_total_minor is None
        ):
            fail("QUOTE_NOT_FIRM", "Firm offer requires an explicitly defined payable total.")
        if head.current_revision_id and head.current_revision_id != quote.id:
            db.add(
                QuoteEvent(
                    quote_revision_id=head.current_revision_id,
                    event_type="SUPERSEDED",
                    reason="Successor offer submitted",
                    actor_user_id=ctx.user.id,
                )
            )
        head.current_revision_id = quote.id
    elif head.current_revision_id != quote.id:
        fail("QUOTE_SUPERSEDED", "Only the current unaccepted offer can be withdrawn.")
    db.add(
        QuoteEvent(
            quote_revision_id=quote.id,
            event_type=action,
            reason=payload.reason,
            actor_user_id=ctx.user.id,
        )
    )
    head.lifecycle_projection = action
    touch(head)
    record(db, ctx, "FREIGHT_QUOTE_" + action, quote, trade, cn)
    return {**view(quote), "lifecycle": action, "head_etag": f'"{head.row_version}"'}


def quote_status(db, quote, at):
    head = exists(db, QuoteHead, quote.quote_head_id)
    lifecycle = "SUPERSEDED" if head.current_revision_id != quote.id else head.lifecycle_projection
    effective = (
        "NOT_YET_VALID"
        if at < aware(quote.valid_from)
        else "EXPIRED"
        if at >= aware(quote.accept_by)
        else "CURRENT"
    )
    return lifecycle, effective


def assumptions(db, ctx, ident, payload):
    trade, cn = planning(db, ctx, ident, "tradetwin.cost_assumptions.prepare", True)
    if ctx.org_id != payer(db, trade)[0]:
        fail("FORBIDDEN", "Only the accepted freight payer prepares private estimates.", status=403)
    value = payload.model_dump(mode="json")
    for component in value["external_cost_components"]:
        for ident in component["applies_to_quote_revision_ids"]:
            q = exists(db, Quote, ident)
            rfq = exists(db, RFQ, exists(db, QuoteHead, q.quote_head_id).rfq_id)
            if rfq.consignment_id != cn.id:
                fail("NOT_FOUND", "Quote not found.", status=404)
            coverage = {c["category_code"]: c["coverage"] for c in q.quote_json["service_coverage"]}
            if coverage.get(component["category"]) in {
                "INCLUDED_IN_QUOTED_PRICE",
                "NOT_APPLICABLE",
            }:
                fail(
                    "COST_CATEGORY_DUPLICATED",
                    "Included/not-applicable costs cannot be externally charged.",
                    status=422,
                )
    row = Assumptions(
        trade_id=trade.id,
        consignment_id=cn.id,
        owner_organisation_id=ctx.org_id,
        revision_number=latest_number(
            db,
            Assumptions,
            Assumptions.consignment_id == cn.id,
            Assumptions.owner_organisation_id == ctx.org_id,
        ),
        assumptions_json=value,
        content_hash=digest(value),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "FREIGHT_COST_ASSUMPTIONS_PREPARED", row, trade, cn)
    return view(row)


def assumption_review(db, ctx, ident, payload):
    row = exists(db, Assumptions, ident)
    trade, cn = planning(db, ctx, row.consignment_id, "tradetwin.cost_assumptions.review", True)
    if ctx.org_id != row.owner_organisation_id:
        fail("NOT_FOUND", "Private assumptions not found.", status=404)
    independent(ctx, row.created_by_user_id)
    result = AssumptionReview(
        assumption_revision_id=row.id,
        decision=payload.decision,
        reason=payload.reason,
        actor_user_id=ctx.user.id,
    )
    db.add(result)
    record(db, ctx, "FREIGHT_COST_ASSUMPTIONS_REVIEWED", result, trade, cn)
    return view(result)
