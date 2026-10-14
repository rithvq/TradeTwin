"""Party, invited-carrier and price access are independent explicit grants."""

from sqlalchemy import select

from app.operations.access import exists, fail, has, lock_trade
from app.operations.models import Consignment
from app.trades.access import participant_role, require
from app.trades.models import Revision, Trade
from app.trades.terms import digest

from .models import RFQ, Invitation


def planning(db, ctx, ident, permission="tradetwin.read", lock=False):
    cn = exists(db, Consignment, ident)
    trade = lock_trade(db, cn.trade_id) if lock else exists(db, Trade, cn.trade_id)
    if lock:
        db.refresh(cn)
    if not participant_role(db, trade.id, ctx.org_id):
        fail("NOT_FOUND", "Planning record not found.", status=404)
    require(db, ctx.user, ctx.org_id, permission, trade.id)
    return trade, cn


def payer(db, trade):
    revision = exists(db, Revision, trade.accepted_revision_id)
    terms = revision.facts_json["commercial_terms"]
    side = terms.get("freight_payer")
    if side not in {"SELLER", "BUYER"}:
        fail(
            "FREIGHT_PAYER_UNRESOLVED",
            "A single seller or buyer freight payer must be established by accepted terms.",
            details={"permitted_next_actions": ["ACCEPT_COMMERCIAL_AMENDMENT"]},
        )
    return revision.facts_json[side.lower() + "_organization_id"], {
        "accepted_revision_id": revision.id,
        "source_field_path": "commercial_terms.freight_payer",
        "accepted_term_value": side,
    }


def price_access(db, ctx, trade, owner=None):
    owner = owner or payer(db, trade)[0]
    return ctx.org_id == owner and has(db, ctx, "freight.price.read", trade.id)


def rfq_access(db, ctx, ident, permission="tradetwin.read", lock=False):
    row = exists(db, RFQ, ident)
    trade = lock_trade(db, row.trade_id) if lock else exists(db, Trade, row.trade_id)
    cn = exists(db, Consignment, row.consignment_id)
    if participant_role(db, trade.id, ctx.org_id):
        require(db, ctx.user, ctx.org_id, permission, trade.id)
        return row, trade, cn, False
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.rfq_id == row.id,
            Invitation.carrier_organisation_id == ctx.org_id,
            Invitation.revoked_at.is_(None),
        )
    )
    if not invitation or row.lifecycle_projection == "DRAFT":
        fail("NOT_FOUND", "RFQ not found.", status=404)
    require(db, ctx.user, ctx.org_id, "freight.rfq.invited.read", trade.id)
    return row, trade, cn, True


def base_context(db, trade, cn):
    from app.compliance import context, governance
    from app.operations.quantities import items

    from .models import LocationHead

    inherited = context.inherited(db, trade, cn)
    owner, basis = payer(db, trade)
    head = db.scalar(select(LocationHead).where(LocationHead.consignment_id == cn.id))
    _, registry, _ = governance.resolve(db, trade.execution_mode)
    commercial_dependencies, _ = context.dependency_snapshot(db, trade, cn, registry)
    # Alerts change planning feasibility, not the carrier's retained fixed offer context.
    commercial_dependencies.pop("corridor_intelligence", None)
    compliance_hash = digest(commercial_dependencies)
    cargo = {
        "gross_weight_kg": cn.plan_json["declared_gross_weight_kg"],
        "volume_m3": cn.plan_json.get("declared_volume_m3"),
        "package_count": cn.plan_json["package_count"],
        "items": [
            {
                "id": i.id,
                "quantity": str(i.allocated_quantity),
                "uqc": i.uqc,
                "cargo": i.cargo_declarations_snapshot,
            }
            for i in items(db, cn.id)
        ],
    }
    result = {
        "schema_version": 1,
        "trade_id": trade.id,
        "consignment_id": cn.id,
        "execution_mode": trade.execution_mode,
        "accepted_trade_revision_id": trade.accepted_revision_id,
        "accepted_terms_hash": inherited["accepted_terms_hash"],
        "coordinating_organisation_id": cn.coordinating_organization_id,
        "freight_payer_organisation_id": owner,
        "freight_payer_basis": basis,
        "current_assignment_id": cn.active_assignment_id,
        "expected_consignment_row_version": cn.row_version,
        "compliance_context_version": context.version(db, trade.id),
        "source_compliance_constraints_hash": compliance_hash,
        "pickup_location_revision_id": head.pickup_location_revision_id if head else None,
        "drop_location_revision_id": head.drop_location_revision_id if head else None,
        "cargo_snapshot": cargo,
        "cargo_hash": digest(cargo),
        "movement_status": cn.movement_status,
        "planning_status": cn.planning_status,
        "inherited": {
            k: inherited[k]
            for k in [
                "movement_purpose",
                "transport_mode",
                "scope",
                "currency",
                "origin_state_code",
                "destination_state_code",
            ]
        },
    }
    # Row versions are concurrency checks, not factual dependencies; comments do not stale runs.
    result["planning_context_hash"] = digest(
        {k: v for k, v in result.items() if k != "expected_consignment_row_version"}
    )
    return result


def invited_scope(db, ctx, cn, permission):
    from app.compliance.clock import instant
    from app.operations.models import Carrier

    if not (
        has(db, ctx, "freight.rfq.invited.read", cn.trade_id)
        or has(db, ctx, "transport.evidence.review", cn.trade_id)
    ):
        return False
    active = db.scalar(
        select(Carrier.id).where(Carrier.organization_id == ctx.org_id, Carrier.active.is_(True))
    )
    invitation = db.scalar(
        select(Invitation.id)
        .join(RFQ)
        .where(
            Invitation.carrier_organisation_id == ctx.org_id,
            Invitation.revoked_at.is_(None),
            RFQ.consignment_id == cn.id,
            RFQ.lifecycle_projection == "OPEN",
            RFQ.response_deadline > instant(db),
        )
    )
    if not active or not invitation:
        return False
    return has(db, ctx, permission, cn.trade_id)
