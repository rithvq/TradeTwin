"""Retain the actual issuance inputs; historical reasons never use today's mutable data."""

from sqlalchemy import select

from app.trades.terms import digest

from .clock import aware
from .models_dashboard import AuthorizationWindow


def candidate(code, value):
    return {"code": code, "at": aware(value).isoformat()}


def retain(db, ctx, authorization, starts, ends, evaluation):
    # These are the very inputs used by issue's max/min, not a second validity calculation.
    summary = {
        "schema_version": "DISPATCH_WINDOW_INPUTS_V1",
        "valid_from": aware(authorization.valid_from).isoformat(),
        "expires_at": aware(authorization.expires_at).isoformat(),
        "start_inputs": starts,
        "expiry_inputs": ends,
        "start_limited_by": sorted(
            {i["code"] for i in starts if i["at"] == aware(authorization.valid_from).isoformat()}
        ),
        "expiry_limited_by": sorted(
            {i["code"] for i in ends if i["at"] == aware(authorization.expires_at).isoformat()}
        ),
        # Frozen evaluation metadata can explain its aggregate boundary without
        # reopening raw observations or consulting subsequently changed evidence.
        "evaluation_deadlines": [
            {"code": d["code"], "at": d["timestamp"]}
            for d in evaluation.coverage_json.get("authority_deadlines", [])
        ]
        + [
            {"code": "OBSERVATION_FRESHNESS", "at": d["fresh_until"]}
            for d in evaluation.coverage_json.get("independent_verification_dimensions", [])
            if d.get("fresh_until")
        ],
    }
    db.add(
        AuthorizationWindow(
            authorization_id=authorization.id,
            summary_json=summary,
            content_hash=digest(summary),
            created_by_user_id=ctx.user.id,
        )
    )


def read(db, authorization):
    row = db.scalar(
        select(AuthorizationWindow).where(AuthorizationWindow.authorization_id == authorization.id)
    )
    if not row:
        return {"detail_status": "NOT_RECORDED", "notice": "Detail not recorded."}
    if digest(row.summary_json) != row.content_hash:
        return {"detail_status": "UNAVAILABLE", "notice": "Detail unavailable."}
    return {
        "detail_status": "RECORDED",
        **row.summary_json,
        "notice": "Expiry boundary is exclusive. Server time controls permission.",
    }
