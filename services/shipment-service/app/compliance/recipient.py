"""Buyer confirmation is evidence, never a rewrite of accepted commercial terms."""

from sqlalchemy import select

from app.operations.access import fail
from app.trades.terms import digest

from . import context
from .ledger import check_context, record, view
from .models_recipient import RecipientConfirmation


def current(db, cn):
    return db.scalar(
        select(RecipientConfirmation)
        .where(RecipientConfirmation.consignment_id == cn.id)
        .order_by(RecipientConfirmation.created_at.desc(), RecipientConfirmation.id.desc())
    )


def prepare(db, ctx, ident, payload):
    trade, cn, side = context.access(db, ctx, ident, "compliance.recipient.confirm", lock=True)
    if side != "BUYER":
        fail("FORBIDDEN", "Only the buyer can supply its own recipient facts.", status=403)
    check_context(ctx, context.version(db, trade.id), payload.expected_context_version)
    inherited = context.inherited(db, trade, cn)
    data = payload.model_dump(mode="json", exclude={"expected_context_version"})
    data["identity_match"] = payload.gstin == inherited["buyer_gstin"]
    data["destination_match"] = (
        payload.destination_state_code == inherited["destination_state_code"]
    )
    data["address_match"] = payload.address_line1 == cn.delivery_address_snapshot.get(
        "address_line1"
    )
    row = RecipientConfirmation(
        trade_id=trade.id,
        consignment_id=cn.id,
        accepted_trade_revision_id=trade.accepted_revision_id,
        confirmation_json=data,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "RECIPIENT_FACTS_CONFIRMED", row)
    return view(row)


def compatible(row, trade):
    if row is None:
        return True  # The accepted buyer-owned snapshot remains the baseline.
    data = row.confirmation_json
    return (
        row.accepted_trade_revision_id == trade.accepted_revision_id
        and all(
            data.get(key) is True
            for key in ("identity_match", "destination_match", "address_match")
        )
        and data.get("confirmation") == "MATCHES_ACCEPTED_SNAPSHOT"
        and (data.get("recipient_category_code") == "REGISTERED_REGULAR")
    )
