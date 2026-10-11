"""Transactional commercial state machine; callers lock the organisation and trade."""

from sqlalchemy import select

from .access import aware, participant_role, require, trade_access
from .errors import TradeError
from .ledger import approvals, audit, make_revision, resolve_parties, revision_facts, trade_view
from .models import Amendment, Approval, Offer, Participant, Revision, Trade, now, uid
from .schemas import TradeFacts
from .terms import merge, validate_publication


def match(ctx, row):
    if ctx.if_match != f'"{row.row_version}"':
        raise TradeError("REVISION_MISMATCH", "This record changed. Reload before saving.", 412)


def touch(trade):
    trade.row_version += 1
    trade.updated_at = now()


def draft_owner(db, ctx, trade, amendment=None):
    side = participant_role(db, trade.id, ctx.org_id)
    require(
        db,
        ctx.user,
        ctx.org_id,
        "trade.propose_amendment" if amendment else "trade.edit_draft",
        trade.id,
        side,
    )
    owner = amendment.proposer_organization_id if amendment else trade.creator_organization_id
    if (
        owner != ctx.org_id
        or (amendment and amendment.status != "DRAFT")
        or (not amendment and (trade.agreement_status != "DRAFT" or trade.accepted_revision_id))
    ):
        raise TradeError(
            "FORBIDDEN", "Only the proposal owner's operators can edit its draft.", 403
        )
    if trade.active_offer_id:
        raise TradeError("OFFER_ACTIVE", "Withdraw the offered terms before editing.", 409)


def create_trade(db, ctx, payload, *, execution_mode="PRODUCTION"):
    role = payload.initiated_by_role
    require(db, ctx.user, ctx.org_id, "trade.create", side=role)
    facts = payload.facts.model_dump(mode="json", exclude_unset=True)
    key = f"{role.lower()}_organization_id"
    if facts.get(key) not in {None, ctx.org_id}:
        raise TradeError("FORBIDDEN", "The initiating party must be your organisation.", 403)
    facts[key] = ctx.org_id
    trade = Trade(
        id=uid(),
        reference=f"TT-AG-{uid()[:8].upper()}",
        creator_organization_id=ctx.org_id,
        initiated_by_role=role,
        created_by=ctx.user.id,
        row_version=1,
        execution_mode=execution_mode,
    )
    db.add(trade)
    db.flush()
    db.add(Participant(trade_id=trade.id, organization_id=ctx.org_id, participant_role=role))
    facts = resolve_parties(db, trade, facts, ctx.org_id)
    revision = make_revision(db, ctx, trade, facts)
    audit(
        db,
        ctx,
        "TRADE_CREATED",
        trade,
        trade,
        revision,
        {"after": "Incomplete commercial draft allowed"},
    )
    db.flush()
    return trade_view(db, ctx, trade)


def patch_draft(db, ctx, trade_id, payload, amendment_id=None):
    trade, _ = trade_access(db, ctx.user, ctx.org_id, trade_id, lock=True)
    match(ctx, trade)
    amendment = db.get(Amendment, amendment_id) if amendment_id else None
    if amendment_id and (
        not amendment
        or amendment.trade_id != trade.id
        or trade.pending_amendment_id != amendment.id
    ):
        raise TradeError("NOT_FOUND", "Proposal not found.", 404)
    draft_owner(db, ctx, trade, amendment)
    base = amendment.proposed_revision_id if amendment else trade.current_revision_id
    if str(payload.base_revision_id) != base:
        raise TradeError("REVISION_MISMATCH", "The candidate revision changed.", 412)
    changes = payload.changes.model_dump(mode="json", exclude_unset=True)
    facts = merge(revision_facts(db, db.get(Revision, base), derived=False), changes)
    if amendment:
        accepted = db.get(Revision, trade.accepted_revision_id).facts_json
        if any(
            facts.get(f"{side}_organization_id") != accepted.get(f"{side}_organization_id")
            for side in ("seller", "buyer")
        ):
            raise TradeError("VALIDATION_FAILED", "Party replacement is outside Phase 1.")
    facts = resolve_parties(db, trade, facts, ctx.org_id)
    revision = make_revision(db, ctx, trade, facts, supersedes=base)
    if amendment:
        amendment.proposed_revision_id = revision.id
    touch(trade)
    audit(
        db,
        ctx,
        "AMENDMENT_DRAFT_SAVED" if amendment else "DRAFT_SAVED",
        amendment or trade,
        trade,
        revision,
        {
            "before_revision_id": base,
            "after_revision_id": revision.id,
            "changed_fields": sorted(changes),
        },
    )
    db.flush()
    return trade_view(db, ctx, trade)


def publish(db, ctx, trade_id, payload, amendment_id=None):
    trade, side = trade_access(db, ctx.user, ctx.org_id, trade_id, lock=True)
    match(ctx, trade)
    amendment = db.get(Amendment, amendment_id) if amendment_id else None
    if amendment_id and (
        not amendment
        or amendment.trade_id != trade.id
        or trade.pending_amendment_id != amendment.id
    ):
        raise TradeError("NOT_FOUND", "Proposal not found.", 404)
    draft_owner(db, ctx, trade, amendment)
    require(db, ctx.user, ctx.org_id, "trade.offer", trade.id, side)
    base = amendment.proposed_revision_id if amendment else trade.current_revision_id
    if str(payload.revision_id) != base:
        raise TradeError("REVISION_MISMATCH", "Publish the current candidate revision.", 412)
    facts = revision_facts(db, db.get(Revision, base), derived=False)
    facts["commercial_terms"] = {
        **(facts.get("commercial_terms") or {}),
        "commercial_valid_until": payload.commercial_valid_until.isoformat(),
    }
    errors = validate_publication(facts)
    if errors:
        raise TradeError(
            "VALIDATION_FAILED", "Complete the commercial terms before publishing.", fields=errors
        )
    # Full validators normalize decimals and UTC timestamps before freezing/hash generation.
    facts = TradeFacts.model_validate(facts).model_dump(mode="json")
    facts = resolve_parties(db, trade, facts, ctx.org_id, complete=True)
    revision = make_revision(
        db, ctx, trade, facts, "AMENDMENT_OFFER" if amendment else "INITIAL_OFFER", base
    )
    offer = Offer(
        id=uid(),
        trade_id=trade.id,
        revision_id=revision.id,
        purpose="AMENDMENT" if amendment else "INITIAL_AGREEMENT",
        published_by=ctx.user.id,
        published_by_organization_id=ctx.org_id,
        expires_at=payload.commercial_valid_until,
    )
    db.add(offer)
    db.flush()
    trade.active_offer_id = offer.id
    if amendment:
        amendment.proposed_revision_id, amendment.offer_id, amendment.status = (
            revision.id,
            offer.id,
            "OFFERED",
        )
    else:
        trade.agreement_status = "OFFERED"
    touch(trade)
    audit(
        db,
        ctx,
        "AMENDMENT_OFFER_PUBLISHED" if amendment else "OFFER_PUBLISHED",
        offer,
        trade,
        revision,
        {"after": "Awaiting separate Seller and Buyer approvals", "amendment_id": amendment_id},
    )
    db.flush()
    return trade_view(db, ctx, trade)


def get_offer_trade(db, ctx, offer_id):
    offer = db.get(Offer, offer_id)
    if not offer:
        raise TradeError("NOT_FOUND", "Offer not found.", 404)
    trade, side = trade_access(db, ctx.user, ctx.org_id, offer.trade_id, lock=True)
    db.refresh(offer)
    return offer, trade, side


def decide(db, ctx, offer_id, payload, decision):
    offer, trade, side = get_offer_trade(db, ctx, offer_id)
    grant = require(db, ctx.user, ctx.org_id, f"order.confirm.{side.lower()}", trade.id, side)
    revision = db.get(Revision, offer.revision_id)
    if str(payload.revision_id) != offer.revision_id or payload.terms_hash != revision.terms_hash:
        raise TradeError(
            "OFFER_REVISION_MISMATCH", "Accept only the exact offered revision and terms hash.", 409
        )
    previous = db.scalar(
        select(Approval).where(Approval.offer_id == offer.id, Approval.participant_role == side)
    )
    if (
        previous
        and previous.decision == decision
        and offer.status in {"ACTIVE", "ACCEPTED", "REJECTED"}
    ):
        return {
            "approval_id": previous.id,
            "party_role": side,
            "approval_progress": approvals(db, offer),
            "agreement_status": trade.agreement_status,
            "accepted_revision_id": trade.accepted_revision_id,
            "offer_status": offer.status,
            "etag": f'"{trade.row_version}"',
        }
    if offer.status == "ACTIVE" and aware(offer.expires_at) <= now():
        raise TradeError("OFFER_EXPIRED", "The offer has expired. Publish new terms.", 409)
    if offer.status != "ACTIVE" or trade.active_offer_id != offer.id:
        raise TradeError("OFFER_INACTIVE", "This offer no longer accepts decisions.", 409)
    if previous:
        raise TradeError("DECISION_ALREADY_RECORDED", "This party's decision is immutable.", 409)
    approval = Approval(
        id=uid(),
        trade_id=trade.id,
        offer_id=offer.id,
        revision_id=revision.id,
        participant_role=side,
        organization_id=ctx.org_id,
        party_snapshot_id=revision.seller_snapshot_id
        if side == "SELLER"
        else revision.buyer_snapshot_id,
        user_id=ctx.user.id,
        capability=grant.capability,
        decision=decision,
        terms_hash=revision.terms_hash,
        reason=getattr(payload, "reason", None),
        authentication_reference=f"profile:{ctx.user.id}:request:{ctx.request_id}",
    )
    db.add(approval)
    db.flush()
    amendment = (
        db.get(Amendment, trade.pending_amendment_id) if trade.pending_amendment_id else None
    )
    if decision == "REJECT":
        offer.status, trade.active_offer_id = "REJECTED", None
        if amendment:
            amendment.status, trade.pending_amendment_id = "REJECTED", None
            trade.current_revision_id = trade.accepted_revision_id
        else:
            trade.agreement_status = "DRAFT"
    elif all(item["decision"] == "ACCEPT" for item in approvals(db, offer)):
        if amendment:
            from app.operations.allocation import accept_amendment

            accept_amendment(db, ctx, trade, revision)
        offer.status, trade.agreement_status = "ACCEPTED", "CONFIRMED"
        trade.accepted_revision_id = revision.id
        trade.active_offer_id = None
        from app.operations.schedules import refresh_triggers

        refresh_triggers(db, ctx, trade)
        if amendment:
            amendment.status, trade.pending_amendment_id = "ACCEPTED", None
    touch(trade)
    audit(
        db,
        ctx,
        f"{side}_{decision}",
        offer,
        trade,
        revision,
        {
            "decision": decision,
            "capability": grant.capability,
            "offer_id": offer.id,
            "reason": getattr(payload, "reason", None),
            "after_status": trade.agreement_status,
        },
    )
    if offer.status == "ACCEPTED":
        audit(
            db,
            ctx,
            "AMENDMENT_ACCEPTED" if amendment else "AGREEMENT_CONFIRMED",
            trade,
            trade,
            revision,
            {"after": "Both parties accepted identical commercial terms; dispatch not assessed"},
        )
    db.flush()
    return {
        "approval_id": approval.id,
        "party_role": side,
        "approval_progress": approvals(db, offer),
        "agreement_status": trade.agreement_status,
        "accepted_revision_id": trade.accepted_revision_id,
        "offer_status": offer.status,
        "etag": f'"{trade.row_version}"',
    }


def withdraw_offer(db, ctx, offer_id, payload):
    offer, trade, side = get_offer_trade(db, ctx, offer_id)
    match(ctx, trade)
    require(db, ctx.user, ctx.org_id, "trade.withdraw_offer", trade.id, side)
    if offer.published_by_organization_id != ctx.org_id:
        raise TradeError(
            "FORBIDDEN", "Only the publishing organisation can withdraw this offer.", 403
        )
    if offer.status != "ACTIVE" or trade.active_offer_id != offer.id:
        raise TradeError("OFFER_INACTIVE", "Confirmed or inactive offers cannot be withdrawn.", 409)
    offer.status, trade.active_offer_id = "WITHDRAWN", None
    db.flush()
    if offer.purpose == "AMENDMENT":
        amendment = db.get(Amendment, trade.pending_amendment_id)
        amendment.status = "WITHDRAWN"
        trade.pending_amendment_id = None
        trade.current_revision_id = trade.accepted_revision_id
        revision = db.get(Revision, trade.accepted_revision_id)
    else:
        trade.agreement_status = "DRAFT"
        revision = make_revision(
            db,
            ctx,
            trade,
            revision_facts(db, db.get(Revision, offer.revision_id), False),
            supersedes=offer.revision_id,
        )
    touch(trade)
    audit(
        db,
        ctx,
        "OFFER_WITHDRAWN",
        offer,
        trade,
        revision,
        {"reason": payload.reason, "offer_id": offer.id},
    )
    db.flush()
    return trade_view(db, ctx, trade)


def create_amendment(db, ctx, trade_id, payload):
    trade, side = trade_access(db, ctx.user, ctx.org_id, trade_id, lock=True)
    match(ctx, trade)
    require(db, ctx.user, ctx.org_id, "trade.propose_amendment", trade.id, side)
    if (
        not trade.accepted_revision_id
        or str(payload.base_accepted_revision_id) != trade.accepted_revision_id
    ):
        raise TradeError("AMENDMENT_BASE_MISMATCH", "Amend the current accepted revision.", 409)
    if trade.pending_amendment_id:
        raise TradeError("AMENDMENT_ACTIVE", "There is already a pending proposal.", 409)
    amendment = Amendment(
        id=uid(),
        trade_id=trade.id,
        base_accepted_revision_id=trade.accepted_revision_id,
        proposer_organization_id=ctx.org_id,
        reason=payload.reason,
        created_by=ctx.user.id,
    )
    db.add(amendment)
    db.flush()
    revision = make_revision(
        db,
        ctx,
        trade,
        revision_facts(db, db.get(Revision, trade.accepted_revision_id), False),
        supersedes=trade.accepted_revision_id,
    )
    amendment.proposed_revision_id, trade.pending_amendment_id = revision.id, amendment.id
    touch(trade)
    audit(
        db,
        ctx,
        "AMENDMENT_CREATED",
        amendment,
        trade,
        revision,
        {"reason": payload.reason, "base_accepted_revision_id": trade.accepted_revision_id},
    )
    db.flush()
    return trade_view(db, ctx, trade)


def withdraw_amendment(db, ctx, amendment_id, payload):
    amendment = db.get(Amendment, amendment_id)
    if not amendment:
        raise TradeError("NOT_FOUND", "Proposal not found.", 404)
    trade, side = trade_access(db, ctx.user, ctx.org_id, amendment.trade_id, lock=True)
    require(db, ctx.user, ctx.org_id, "trade.propose_amendment", trade.id, side)
    if amendment.proposer_organization_id != ctx.org_id:
        raise TradeError("FORBIDDEN", "Only the proposer can withdraw this amendment.", 403)
    if amendment.status not in {"DRAFT", "OFFERED"} or trade.pending_amendment_id != amendment.id:
        raise TradeError("AMENDMENT_INACTIVE", "This proposal is no longer pending.", 409)
    if amendment.offer_id:
        db.get(Offer, amendment.offer_id).status = "WITHDRAWN"
    amendment.status, trade.active_offer_id, trade.pending_amendment_id = "WITHDRAWN", None, None
    trade.current_revision_id = trade.accepted_revision_id
    touch(trade)
    audit(
        db,
        ctx,
        "AMENDMENT_WITHDRAWN",
        amendment,
        trade,
        db.get(Revision, trade.accepted_revision_id),
        {"reason": payload.reason, "after": "Accepted agreement unchanged"},
    )
    db.flush()
    return trade_view(db, ctx, trade)
