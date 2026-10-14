"""Read an operator-managed generation outside business backups; never auto-recreate it."""

import json
import os
from pathlib import Path
from uuid import UUID

from app.operations.access import fail

from .models import Deployment


def external():
    filename = os.getenv("TRADETWIN_OPERATIONAL_FENCE_FILE")
    if not filename:
        return {"state": "UNCONFIGURED", "deployment_id": None, "generation_id": None}
    try:
        value = json.loads(Path(filename).read_text(encoding="utf-8"))
        return {
            "state": "CONFIGURED",
            "deployment_id": str(UUID(value["deployment_id"])),
            "generation_id": str(UUID(value["generation_id"])),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "UNAVAILABLE", "deployment_id": None, "generation_id": None}


def required():
    return os.getenv("TRADETWIN_REQUIRE_QUALIFICATION", "false").lower() == "true"


def dependency(db):
    value = external()
    row = db.get(Deployment, value["deployment_id"]) if value["deployment_id"] else None
    return {
        **value,
        "qualification_enforced": required(),
        "recorded_generation_id": row.operational_generation_id if row else None,
        "controls_version": row.row_version if row else None,
        "activation_state": row.activation_state if row else "UNQUALIFIED",
        "controls": row.controls_json if row else {},
    }


def guard(db, trade, action):
    from sqlalchemy import select

    from .models_demo import Workspace

    demonstration = db.scalar(select(Workspace).where(Workspace.trade_id == trade.id))
    if demonstration and demonstration.state == "SEALED":
        fail(
            "DEMO_WORKSPACE_SEALED",
            "This demonstration is sealed; binding and movement need a new successor.",
        )
    value = dependency(db)
    if value["state"] != "UNCONFIGURED" and (
        value["state"] != "CONFIGURED" or value["recorded_generation_id"] != value["generation_id"]
    ):
        fail(
            "OPERATIONAL_GENERATION_STALE",
            "Deployment generation is unregistered or changed. Reconcile and requalify.",
        )
    if value["controls"].get(
        "pause_movement_permissions" if action == "MOVEMENT" else "pause_binding_actions"
    ):
        fail(
            "OPERATIONAL_PAUSE",
            "New permissions and bindings are paused; factual reporting remains available.",
        )
    if trade.execution_mode == "PRODUCTION" and required():
        # Pilot admission and complete recovery assurance are not implemented yet.
        # A fail-closed fence must not masquerade as a production authorisation engine.
        fail(
            "PILOT_NOT_QUALIFIED",
            "Production binding requires qualified pilot admission and recovery assurance.",
        )
