"""Exact-build assurance records. Absence of a runner observation is UNKNOWN, not PASS."""

import importlib.metadata
import os
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, text

from app.compliance.clock import aware, instant
from app.document_desk.models import Job, Outbox
from app.operations.access import exists, fail
from app.trades.access import require
from app.trades.terms import digest

from . import fence
from .models import (
    CheckDefinition,
    CheckResult,
    Deployment,
    DeploymentEvent,
    Manifest,
    ManualReview,
    Qualification,
    ReadinessRun,
    Scope,
    ScopeApproval,
)

SUITE = "PRODUCT_ASSURANCE_V1"
AUTOMATED = (
    "COMMERCIAL_CONCURRENCY",
    "QUANTITIES_UQC",
    "BOOKING_ASSIGNMENT",
    "GUARDED_MOVEMENT",
    "RECEIPT_PAYMENT_INDEPENDENCE",
    "DOCUMENT_QUARANTINE_PROVENANCE",
    "REVIEW_MAPPING",
    "SIGNATURE_PROVIDER_OBSERVATION",
    "EVIDENCE_BINDINGS",
    "INDEPENDENT_REVIEW",
    "TOKEN_FRESHNESS",
    "NO_ALTERNATE_MOVEMENT_PATH",
    "COST_DETERMINISM",
    "QUOTE_COMMITMENT",
    "CAP_TOMBSTONES",
    "SOURCE_OUTAGE",
    "EXECUTABLE_RECOVERY",
    "TENANT_MODE_ISOLATION",
    "NEGATIVE_PERMISSIONS",
    "CRASH_OUTBOX",
    "STALE_WORKER",
    "MIGRATIONS",
    "PRODUCTION_RESTORE_FENCE",
    "LOG_EXPORT_REDACTION",
    "PARSER_RESOURCE_LIMITS",
)
MANUAL = (
    "PILOT_RULE_PACKS",
    "ADAPTER_ACCESS_LICENCES",
    "PARTICIPANTS_LIMITS",
    "RUNBOOK_ESCALATION",
)


def require_read(db, ctx):
    require(db, ctx.user, ctx.org_id, "readiness.read")
    bound(ctx)


def operator_organisations():
    try:
        return sorted(
            {
                str(UUID(value.strip()))
                for value in os.getenv("TRADETWIN_CONTROL_ORGANISATION_IDS", "").split(",")
                if value.strip()
            }
        )
    except ValueError:
        fail(
            "OPERATOR_BINDING_UNAVAILABLE",
            "Server operator bindings are invalid; controls remain protected.",
            status=503,
        )


def bound(ctx):
    if ctx.org_id not in operator_organisations():
        fail(
            "OPERATOR_NOT_BOUND",
            "This organisation is not bound to deployment controls by the server operator.",
            status=403,
        )


def control(db, ctx, permission):
    require(db, ctx.user, ctx.org_id, permission)
    bound(ctx)


def build():
    from app.document_desk.jobs import configuration

    # Include the actual service source, normalized for Windows/Linux determinism.
    service = Path(__file__).resolve().parents[2]
    files = sorted(service.rglob("*.py"))
    source = sha256()
    for path in files:
        source.update(str(path.relative_to(service)).replace("\\", "/").encode())
        source.update(path.read_bytes().replace(b"\r\n", b"\n"))
    root = next((parent for parent in service.parents if (parent / "apps/web").is_dir()), None)
    web = root / "apps/web" if root else None
    frontend = sha256()
    for folder in ("app", "components", "hooks", "lib", "types"):
        for path in sorted((web / folder).rglob("*")) if web else []:
            if path.is_file() and path.suffix in {".ts", ".tsx", ".css"}:
                frontend.update(path.relative_to(web).as_posix().encode())
                frontend.update(path.read_bytes().replace(b"\r\n", b"\n"))
    frontend_available = web is not None
    return {
        "shipment_source_hash": source.hexdigest(),
        "frontend_source_hash": frontend.hexdigest() if frontend_available else None,
        "frontend_manifest_coverage": "SOURCE_ONLY"
        if frontend_available
        else "UNAVAILABLE_IN_SERVICE_IMAGE",
        "dependencies": {
            p: importlib.metadata.version(p)
            for p in ("pydantic", "sqlalchemy", "alembic", "shapely", "networkx")
        },
        "parser_limits": configuration(),
        "qualification_enforced": fence.required(),
        "operator_organisation_ids": operator_organisations(),
        "supported_recovery_profile_codes": [],
        "runner_version": SUITE,
    }


def definition(code):
    return {
        "check_code": code,
        "mandatory": True,
        "version": SUITE,
        "provenance": "MANUAL_REVIEW" if code in MANUAL else "REGISTERED_RUNNER",
        "applicability": "ALL",
        "client_outcome_accepted": False,
    }


def context(db, ctx):
    require(db, ctx.user, ctx.org_id, "readiness.read")
    current = fence.external()
    if current["state"] != "CONFIGURED":
        return {
            "fence": current,
            "qualification_outcome": "NOT_QUALIFIED",
            "manifest": None,
            "limitations": ["Configure an external generation outside the business restore set."],
        }
    bound(ctx)
    row = db.get(Deployment, current["deployment_id"])
    if not row:
        row = Deployment(
            deployment_id=current["deployment_id"],
            operational_generation_id=current["generation_id"],
            controls_json={},
        )
        db.add(row)
        db.flush()
    if row.operational_generation_id != current["generation_id"]:
        return {
            "fence": current,
            "qualification_outcome": "RESTORE_RECONCILIATION_REQUIRED",
            "manifest": None,
            "limitations": [
                "External generation differs from database; no old qualification is current."
            ],
        }
    schema = db.scalar(text("SELECT version_num FROM trade_alembic_version"))
    from app.compliance.governance import resolve

    _, registry, _ = resolve(db, "SIMULATION")
    value = {
        **build(),
        "deployment_id": row.deployment_id,
        "operational_generation_id": row.operational_generation_id,
        "database_migration": schema,
        "simulation_rule_registry_manifest": registry,
        "controls_version": row.row_version,
        "definition_hashes": {code: digest(definition(code)) for code in (*AUTOMATED, *MANUAL)},
        "qualification_type": "DEMO",
        "execution_mode": "SIMULATION",
        "coverage": "BOUNDED_PHASE7_FOUNDATION",
        "production_adapter_access": "NOT_ASSESSED",
    }
    fingerprint = digest(value)
    manifest = (
        db.get(Manifest, row.current_manifest_revision_id)
        if row.current_manifest_revision_id
        else None
    )
    if not manifest or manifest.content_hash != fingerprint:
        manifest = Manifest(
            deployment_id=row.deployment_id,
            operational_generation_id=row.operational_generation_id,
            qualification_type="DEMO",
            execution_mode="SIMULATION",
            manifest_json=value,
            content_hash=fingerprint,
            created_by_user_id=ctx.user.id,
        )
        db.add(manifest)
        db.flush()
        row.current_manifest_revision_id = manifest.id
        row.current_qualified_run_id = None
    return {
        "fence": current,
        "deployment_id": row.deployment_id,
        "manifest_revision_id": manifest.id,
        "manifest_hash": fingerprint,
        "manifest": value,
        "etag": f'"{row.row_version}"',
        "qualification_outcome": "NOT_QUALIFIED",
        "activation_state": row.activation_state,
        "controls": row.controls_json,
        "limitations": [
            "A passing unit test does not qualify an unmeasured deployment.",
            "Executable recovery remains unavailable.",
        ],
    }


def enqueue(db, ctx, ident, payload):
    control(db, ctx, "readiness.run")
    current = context(db, ctx)
    if not current["manifest"] or current["manifest_hash"] != payload.expected_manifest_hash:
        fail("MANIFEST_CHANGED", "Use the exact current deployment manifest.", status=412)
    active = db.scalar(
        select(func.count())
        .select_from(ReadinessRun)
        .where(
            ReadinessRun.requested_by_user_id == ctx.user.id,
            ReadinessRun.job_state.in_(["QUEUED", "RUNNING"]),
        )
    )
    if active >= 2:
        fail(
            "JOB_RATE_LIMITED",
            "At most two assurance jobs may be outstanding per recipient.",
            status=429,
        )
    row = ReadinessRun(
        manifest_revision_id=current["manifest_revision_id"],
        manifest_hash=current["manifest_hash"],
        runner_version=SUITE,
        requested_by_user_id=ctx.user.id,
        requested_by_organisation_id=ctx.org_id,
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    job = Job(
        stage="READINESS_CHECK",
        input_fingerprint=digest({"readiness_run_id": row.id}),
        pipeline_version=SUITE,
        schema_version="READINESS_RUN_V1",
        configuration_hash=row.manifest_hash,
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json={"readiness_run_id": row.id},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    row.job_id = job.id
    db.add(Outbox(job_id=job.id))
    return {"id": row.id, "job_state": row.job_state, "manifest_hash": row.manifest_hash}


def complete(db, ctx, ident):
    control(db, ctx, "readiness.run")
    row = exists(db, ReadinessRun, ident)
    if row.completed_at:
        return
    current = context(db, ctx)
    if current.get("manifest_hash") != row.manifest_hash:
        fail("MANIFEST_CHANGED", "The deployment changed before assurance completion.", status=412)
    checked = instant(db)
    results = []
    for code in (*AUTOMATED, *MANUAL):
        expected = definition(code)
        check = db.scalar(
            select(CheckDefinition).where(
                CheckDefinition.check_code == code, CheckDefinition.version == SUITE
            )
        )
        if not check:
            check = CheckDefinition(
                check_code=code,
                version=SUITE,
                definition_json=expected,
                content_hash=digest(expected),
                created_by_user_id=ctx.user.id,
            )
            db.add(check)
            db.flush()
        outcome = "FAIL" if code == "EXECUTABLE_RECOVERY" else "UNKNOWN"
        observed = {
            "reason": "Recovery repricing, amendments and guarded resume are unavailable."
            if outcome == "FAIL"
            else "No registered deployment-scoped observation retained for this suite.",
            "build_manifest_hash": row.manifest_hash,
        }
        result = {
            "check_code": code,
            "definition_hash": check.content_hash,
            "outcome": outcome,
            "observed": observed,
        }
        db.add(
            CheckResult(
                run_id=row.id,
                definition_revision_id=check.id,
                outcome=outcome,
                observed_json=observed,
                evidence_refs_json=[],
                provenance=expected["provenance"],
                checked_at=checked,
                valid_until=checked + timedelta(hours=24),
                limitations_json=[
                    "Local tests are reported separately, not as deployment qualification."
                ],
                content_hash=digest(result),
                created_by_user_id=ctx.user.id,
            )
        )
        results.append(result)
    row.job_state, row.qualification_outcome = "COMPLETED", "NOT_QUALIFIED"
    row.result_hash = digest({"manifest_hash": row.manifest_hash, "results": results})
    row.completed_at, row.valid_until = checked, checked + timedelta(hours=24)


def read(db, ctx, ident):
    require_read(db, ctx)
    row = exists(db, ReadinessRun, ident)
    if row.requested_by_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Readiness run not found.", status=404)
    return {
        "id": row.id,
        "manifest_hash": row.manifest_hash,
        "job_state": row.job_state,
        "result_hash": row.result_hash,
        "qualification_outcome": row.qualification_outcome,
        "valid_until": aware(row.valid_until).isoformat() if row.valid_until else None,
        "checks": [
            {
                "id": c.id,
                "definition_id": c.definition_revision_id,
                "check_code": db.get(CheckDefinition, c.definition_revision_id).check_code,
                "outcome": c.outcome,
                "provenance": c.provenance,
                "observation": c.observed_json,
                "limitations": c.limitations_json,
            }
            for c in db.scalars(
                select(CheckResult).where(CheckResult.run_id == row.id).order_by(CheckResult.id)
            )
        ],
    }


def manual(db, ctx, ident, payload):
    control(db, ctx, "readiness.manual.prepare")
    read(db, ctx, ident)
    run = exists(db, ReadinessRun, ident)
    check = exists(db, CheckDefinition, str(payload.check_definition_id))
    if (
        check.check_code not in MANUAL
        or not run.result_hash
        or payload.input_hash != run.result_hash
    ):
        fail(
            "MANIFEST_CHANGED",
            "A manual statement must reference this completed result and a manual definition.",
            status=412,
        )
    # Evidence references are restricted to retained results for this exact run.
    allowed = set(db.scalars(select(CheckResult.id).where(CheckResult.run_id == run.id)))
    if not {str(i) for i in payload.evidence_refs} <= allowed:
        fail("NOT_FOUND", "Review evidence not found in this run.", status=404)
    row = ManualReview(
        run_id=run.id,
        definition_revision_id=check.id,
        input_hash=run.result_hash,
        review_statement=payload.review_statement,
        evidence_refs_json=[str(i) for i in payload.evidence_refs],
        content_hash=digest(payload.model_dump(mode="json")),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    return {"id": row.id, "statement_retained": True, "qualification_changed": False}


def qualify(db, ctx, ident, payload):
    control(db, ctx, "readiness.review")
    read(db, ctx, ident)
    run = exists(db, ReadinessRun, ident)
    if ctx.user.id == run.requested_by_user_id:
        fail(
            "INDEPENDENT_REVIEW_REQUIRED",
            "The runner principal cannot qualify its own result.",
            status=403,
        )
    if (
        run.result_hash != payload.result_hash
        or not run.completed_at
        or instant(db) >= aware(run.valid_until)
    ):
        fail("MANIFEST_CHANGED", "Review the exact completed, unexpired result.", status=412)
    if context(db, ctx).get("manifest_hash") != run.manifest_hash:
        fail("MANIFEST_CHANGED", "Deployment changed since this run.", status=412)
    if payload.decision == "APPROVE_QUALIFICATION":
        if run.qualification_outcome != "PASS":
            fail("QUALIFICATION_BLOCKED", "Mandatory FAIL or UNKNOWN evidence cannot be qualified.")
    row = Qualification(
        run_id=run.id,
        result_hash=run.result_hash,
        decision=payload.decision,
        reason=payload.reason,
        reviewer_user_id=ctx.user.id,
        reviewer_organisation_id=ctx.org_id,
        valid_until=run.valid_until,
    )
    db.add(row)
    db.flush()
    return {
        "id": row.id,
        "decision": row.decision,
        "qualified": payload.decision == "APPROVE_QUALIFICATION",
    }


def pause(db, ctx, ident, payload):
    control(db, ctx, "deployment.pause")
    current = context(db, ctx)
    if current.get("deployment_id") != ident:
        fail("NOT_FOUND", "Deployment not found.", status=404)
    row = exists(db, Deployment, ident)
    if ctx.if_match != f'"{row.row_version}"':
        fail("MANIFEST_CHANGED", "Reload the current deployment ETag.", status=412)
    if not payload.pause_binding_actions and not payload.pause_movement_permissions:
        fail(
            "VALIDATION_ERROR",
            "Pause at least one control; reactivation requires qualification.",
            status=422,
        )
    row.controls_json = {
        "pause_binding_actions": payload.pause_binding_actions
        or row.controls_json.get("pause_binding_actions", False),
        "pause_movement_permissions": payload.pause_movement_permissions
        or row.controls_json.get("pause_movement_permissions", False),
    }
    row.row_version += 1
    row.activation_state = "PAUSED"
    row.current_qualified_run_id = None
    event = {
        "reason": payload.reason,
        "controls": row.controls_json,
        "external_generation_id": row.operational_generation_id,
        "physical_stop_commanded": False,
        "factual_reporting_preserved": True,
    }
    db.add(
        DeploymentEvent(
            deployment_id=row.deployment_id,
            event_type="PAUSED",
            event_json=event,
            content_hash=digest(event),
            created_by_user_id=ctx.user.id,
        )
    )
    return {"deployment_id": row.deployment_id, "etag": f'"{row.row_version}"', **event}


def scope(db, ctx, ident, payload):
    control(db, ctx, "pilot.scope.prepare")
    from app.trades.models import Organization

    for org in [*payload.organisation_ids, *payload.carrier_organisation_ids]:
        exists(db, Organization, str(org))
    # Unknown policy references are not accepted as deployable scope evidence.
    from app.compliance.models import Pack
    from app.corridor.models import Policy

    for model, refs in [
        (Pack, payload.supported_rule_pack_refs),
        (Pack, payload.allowed_proof_policy_refs),
        (Policy, payload.source_coverage_policy_refs),
    ]:
        for ref in refs:
            exists(db, model, str(ref))
    value = payload.model_dump(mode="json")
    row = Scope(
        scope_code=payload.scope_code,
        version=payload.version,
        scope_json=value,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        content_hash=digest(value),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    return {"id": row.id, "content_hash": row.content_hash, "scope": value, "active": False}


def review_scope(db, ctx, ident, payload):
    control(db, ctx, "pilot.scope.review")
    row = exists(db, Scope, ident)
    if row.created_by_user_id == ctx.user.id:
        fail(
            "INDEPENDENT_REVIEW_REQUIRED",
            "Scope preparation and review require different principals.",
            status=403,
        )
    if row.content_hash != payload.content_hash:
        fail("MANIFEST_CHANGED", "Scope content hash changed.", status=412)
    result = ScopeApproval(
        scope_revision_id=row.id,
        content_hash=row.content_hash,
        decision=payload.decision,
        actor_user_id=ctx.user.id,
        actor_organisation_id=ctx.org_id,
        reason=payload.reason,
    )
    db.add(result)
    db.flush()
    return {"id": result.id, "decision": result.decision, "active": False}


def activate(db, ctx, ident, payload):
    control(db, ctx, "deployment.activate")
    current = context(db, ctx)
    if (
        current.get("deployment_id") != ident
        or current.get("manifest_hash") != payload.manifest_hash
    ):
        fail("MANIFEST_CHANGED", "Use the exact current deployment manifest.", status=412)
    decision = exists(db, Qualification, str(payload.qualification_decision_id))
    run = exists(db, ReadinessRun, str(payload.qualified_run_id))
    if (
        decision.run_id != run.id
        or decision.decision != "APPROVE_QUALIFICATION"
        or run.qualification_outcome != "PASS"
    ):
        fail("QUALIFICATION_BLOCKED", "A completed independent qualification is required.")
    fail(
        "QUALIFICATION_BLOCKED",
        "Pilot admission and executable recovery are unavailable; activation remains protected.",
    )


def health(db, ctx, ident):
    require_read(db, ctx)
    if fence.external().get("deployment_id") != ident:
        fail("NOT_FOUND", "Deployment not found.", status=404)
    db.execute(text("SELECT 1"))
    pending = db.scalar(
        select(func.count()).select_from(Outbox).where(Outbox.published_at.is_(None))
    )
    return {
        "deployment_id": ident,
        "observed_at": instant(db).isoformat(),
        "database": "AVAILABLE",
        "unpublished_outbox_count": pending,
        "providers": "NOT_ASSESSED",
        "backup_health": "NOT_ASSESSED",
        "worker_health": "NOT_ASSESSED",
        "business_readiness": "NOT_QUALIFIED",
    }
