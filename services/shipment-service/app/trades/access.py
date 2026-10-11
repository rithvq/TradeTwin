"""A business role is a view filter. Explicit membership grants authorize actions."""

from datetime import UTC

from sqlalchemy import or_, select
from tradetwin_security import identity

from .errors import TradeError
from .models import Grant, Membership, Offer, Organization, Participant, Trade, User, now, uid


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def actor(db):
    principal = identity.get()
    if not principal or not principal.get("id"):
        raise TradeError("AUTHENTICATION_REQUIRED", "Sign in to your profile.", 401)
    subject = str(principal["id"])
    user = db.scalar(select(User).where(User.identity_subject == subject))
    if not user:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        db.execute(
            insert(User)
            .values(
                id=uid(),
                identity_subject=subject,
                display_name=str(principal.get("name") or "TradeTwin member"),
                email=str(principal.get("email") or ""),
                active=True,
            )
            .on_conflict_do_nothing(index_elements=["identity_subject"])
        )
        user = db.scalar(select(User).where(User.identity_subject == subject))
    if not user.active:
        raise TradeError("FORBIDDEN", "This account is inactive.", 403)
    return user


def membership(db, user, organization_id):
    member = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == organization_id,
            Membership.status == "ACTIVE",
        )
    )
    if not member:
        raise TradeError("FORBIDDEN", "An active organisation membership is required.", 403)
    return member


def grants(db, member, trade_id=None):
    return list(
        db.scalars(
            select(Grant).where(
                Grant.membership_id == member.id,
                Grant.revoked_at.is_(None),
                or_(Grant.expires_at.is_(None), Grant.expires_at > now()),
                or_(Grant.trade_id.is_(None), Grant.trade_id == trade_id),
            )
        )
    )


def require(db, user, organization_id, permission, trade_id=None, side=None):
    member = membership(db, user, organization_id)
    found = next(
        (
            grant
            for grant in grants(db, member, trade_id)
            if grant.permission_code == permission
            and (not side or grant.capability.startswith(f"{side}_"))
        ),
        None,
    )
    if not found:
        raise TradeError("FORBIDDEN", f"Missing capability for {permission}.", 403)
    return found


def organization(db, user, organization_id, permission="organization.read", lock=False):
    require(db, user, organization_id, permission)
    query = select(Organization).where(Organization.id == organization_id)
    result = db.scalar(query.with_for_update() if lock else query)
    if not result:
        raise TradeError("NOT_FOUND", "Organisation not found.", 404)
    return result


def participant_role(db, trade_id, organization_id):
    return db.scalar(
        select(Participant.participant_role).where(
            Participant.trade_id == trade_id, Participant.organization_id == organization_id
        )
    )


def trade_access(db, user, organization_id, trade_id, permission="trade.read", lock=False):
    membership(db, user, organization_id)
    query = select(Trade).where(Trade.id == trade_id)
    trade = db.scalar(query.with_for_update() if lock else query)
    side = participant_role(db, trade_id, organization_id)
    if not trade or not side:
        raise TradeError("NOT_FOUND", "Trade not found.", 404)
    # The other party cannot inspect an unpublished initial draft.
    if (
        not trade.accepted_revision_id
        and trade.agreement_status == "DRAFT"
        and organization_id != trade.creator_organization_id
        and not db.scalar(select(Offer.id).where(Offer.trade_id == trade_id).limit(1))
    ):
        raise TradeError("NOT_FOUND", "Trade not found.", 404)
    require(db, user, organization_id, permission, trade_id, side)
    return trade, side
