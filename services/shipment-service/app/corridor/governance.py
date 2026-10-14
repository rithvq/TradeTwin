"""Independent exact-hash review uses the existing regulation capabilities and audit."""

from sqlalchemy import func, select

from app.compliance.clock import aware, instant
from app.compliance.ledger import independent, record, view
from app.operations.access import exists, fail
from app.trades.access import require
from app.trades.models import User
from app.trades.terms import digest

from .models import GovernanceAction, Mapping, Policy


def active(db, row, at=None):
    at = at or instant(db)
    if not aware(row.effective_from) <= at < aware(row.effective_until):
        return False
    return published(db, row)


def published(db, row):
    column = (
        GovernanceAction.policy_revision_id
        if isinstance(row, Policy)
        else GovernanceAction.mapping_revision_id
    )
    actions = list(
        db.scalars(
            select(GovernanceAction)
            .where(column == row.id)
            .order_by(GovernanceAction.sequence_number)
        )
    )
    if not actions or actions[-1].action != "PUBLISHED":
        return False
    for action in actions:
        if action.action != "APPROVED":
            continue
        user = db.get(User, action.actor_user_id)
        if not user or not user.active:
            return False
        try:
            require(db, user, action.actor_organisation_id, "regulation.pack.review")
        except Exception as exc:
            from app.trades.errors import TradeError

            if not isinstance(exc, TradeError):
                raise
            return False
    return any(a.action == "APPROVED" and a.content_hash == row.content_hash for a in actions)


def create(db, ctx, ident, payload, model=Policy):
    require(db, ctx.user, ctx.org_id, "regulation.pack.prepare")
    data = payload.model_dump(mode="json")
    row = model(
        environment=payload.environment,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
        **(
            {"policy_code": payload.policy_code, "policy_json": data}
            if model is Policy
            else {
                "endpoint_contract_version": payload.endpoint_contract_version,
                "mapping_json": data,
            }
        ),
    )
    db.add(row)
    record(db, ctx, "CORRIDOR_GOVERNANCE_PREPARED", row)
    return view(row)


def mapping(db, ctx, ident, payload):
    return create(db, ctx, ident, payload, Mapping)


def decide(db, ctx, ident, payload, model=Policy, publish=False):
    require(
        db, ctx.user, ctx.org_id, "regulation.pack.publish" if publish else "regulation.pack.review"
    )
    row = exists(db, model, ident)
    if payload.content_hash != row.content_hash:
        fail("EXACT_HASH_REQUIRED", "Review the exact retained revision.", status=412)
    independent(ctx, row.created_by_user_id)
    column = (
        GovernanceAction.policy_revision_id
        if model is Policy
        else GovernanceAction.mapping_revision_id
    )
    history = list(
        db.scalars(
            select(GovernanceAction)
            .where(column == row.id)
            .order_by(GovernanceAction.sequence_number)
        )
    )
    if publish:
        if not history or history[-1].action != "APPROVED":
            fail("INDEPENDENT_REVIEW_REQUIRED", "An exact current approval is required.")
        reviewer = exists(db, User, history[-1].actor_user_id)
        require(db, reviewer, history[-1].actor_organisation_id, "regulation.pack.review")
        if not reviewer.active:
            fail("INDEPENDENT_REVIEW_REQUIRED", "The approving account is inactive.")
    action = "PUBLISHED" if publish else "APPROVED" if payload.decision == "APPROVE" else "RETURNED"
    kwargs = {column.key: row.id}
    db.add(
        GovernanceAction(
            **kwargs,
            sequence_number=(
                db.scalar(
                    select(func.max(GovernanceAction.sequence_number)).where(column == row.id)
                )
                or 0
            )
            + 1,
            action=action,
            content_hash=row.content_hash,
            actor_user_id=ctx.user.id,
            actor_organisation_id=ctx.org_id,
            reason=payload.reason,
        )
    )
    if publish:
        from .projection import bump_scopes

        bump_scopes(
            db,
            row.environment,
            ["state:" + s for s in row.policy_json["state_codes"]]
            if model is Policy and row.policy_json["state_codes"]
            else ["*"],
        )
    record(db, ctx, "CORRIDOR_GOVERNANCE_" + action, row)
    return {**view(row), "action": action}
