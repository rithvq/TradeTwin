"""Registered isolated backup/fence drill; no production backup or restore is performed."""

import sqlite3
from time import monotonic
from uuid import uuid4

from app.compliance.clock import instant
from app.operations.access import fail
from app.trades.terms import digest

from . import assurance, fence
from .models import Rehearsal


def run(db, ctx, ident, payload):
    assurance.control(db, ctx, "deployment.restore.rehearse")
    current = assurance.context(db, ctx)
    if current.get("deployment_id") != ident:
        fail("NOT_FOUND", "Deployment not found.", status=404)
    start = monotonic()
    before_generation, external_generation = str(uuid4()), str(uuid4())
    source, backup, restored = (sqlite3.connect(":memory:") for _ in range(3))
    try:
        source.execute("CREATE TABLE drill (id INTEGER PRIMARY KEY, value TEXT)")
        source.execute("INSERT INTO drill VALUES (1, ?)", (before_generation,))
        source.commit()
        source.backup(backup)
        source.execute("INSERT INTO drill VALUES (2, 'post-backup-event')")
        source.commit()
        backup.backup(restored)
        stored_generation = restored.execute("SELECT value FROM drill WHERE id = 1").fetchone()[0]
        restored_count = restored.execute("SELECT COUNT(*) FROM drill").fetchone()[0]
        outcomes = {
            "backup_marker_restored": restored_count == 1,
            "external_generation_not_restored": stored_generation != external_generation,
            "post_backup_gap_detected": restored_count
            != source.execute("SELECT COUNT(*) FROM drill").fetchone()[0],
        }
    finally:
        for connection in (source, backup, restored):
            connection.close()
    value = {
        "profile": payload.registered_rehearsal_profile_code,
        "observed_at": instant(db).isoformat(),
        "measurements": {"isolated_drill_elapsed_seconds": round(monotonic() - start, 6)},
        "assertions": outcomes,
        "outcome": "PASS" if all(outcomes.values()) else "FAIL",
        "production_rpo_seconds": None,
        "production_rto_seconds": None,
        "production_restored": False,
        "operational_generation_changed": False,
        "production_target_rpo_seconds": 900,
        "production_target_rto_seconds": 3600,
        "limitations": [
            "In-memory SQLite marker exercise only; production RPO/RTO remain unmeasured.",
            "Real restores require independent generation rotation and gap reconciliation.",
        ],
    }
    row = Rehearsal(
        deployment_id=ident,
        rehearsal_json=value,
        content_hash=digest(value),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    return {
        "id": row.id,
        **value,
        "qualification_changed": False,
        "external_fence": fence.external()["state"],
    }
