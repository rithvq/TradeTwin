"""Retain a minimal rejected-command observation after business rollback, never a permission."""

import logging

from app.trades.errors import TradeError
from app.trades.ledger import audit
from app.trades.transactions import context, mutate

from .access import consignment


def recorded_mutation(request, db, operation, payload, **options):
    try:
        return mutate(request, db, operation, payload, **options)
    except TradeError as error:
        if payload.event_type not in {"PICKUP_CONFIRMED", "DEPARTED"}:
            raise
        # The original command is already rolled back. Recheck current authority before
        # recording metadata in a separate transaction. Never retain the submitted payload.
        try:
            ctx = context(request, db)
            ident = request.path_params["ident"]
            trade, cn, _ = consignment(db, ctx, str(ident), "shipment.event.record", lock=True)
            audit(
                db,
                ctx,
                "DISPATCH_MOVEMENT_REJECTED",
                cn,
                trade=trade,
                consignment=cn,
                summary={
                    "action": payload.event_type,
                    "reason_code": error.code,
                    "client_event_id": str(payload.client_event_id),
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            logging.getLogger(__name__).warning("Movement rejection observation unavailable")
        raise
