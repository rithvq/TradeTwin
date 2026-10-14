"""Registered, actor-bound guided demo. No impersonation, arbitrary commands or magic approvals."""

from datetime import timedelta

from sqlalchemy import select

from app.compliance.clock import aware, instant
from app.operations.access import exists, fail
from app.trades.access import require
from app.trades.agreements import create_trade
from app.trades.models import Trade
from app.trades.schemas import TradeCreate
from app.trades.terms import digest

from . import workspace
from .models_demo import (
    Checkpoint,
    Clock,
    ClockEvent,
    DemoRun,
    Measurement,
    Scenario,
    StepReceipt,
    Workspace,
)

CATALOG = {
    "schema_version": 1,
    "scenario_code": "BOUNDED_JOURNEY_V1",
    "version": "1",
    "execution_mode": "SIMULATION",
    "scope": "BOUNDED_FOUNDATION_NOT_FULL_PHASE7",
    "steps": [
        {
            "step_code": "CREATE_SIMULATION_DRAFT",
            "operation_id": "CREATE_SIMULATION_DRAFT",
            "required_permission": "trade.create",
        },
        {
            "step_code": "READ_INDEPENDENT_DIMENSIONS",
            "operation_id": "READ_WORKSPACE",
            "required_permission": "trade.read",
        },
        {
            "step_code": "EXECUTABLE_RECOVERY",
            "operation_id": "ASSERT_RECOVERY_AVAILABLE",
            "required_permission": "consignment.read",
        },
    ],
    "limitations": [
        "Commercial, document, transport and payment actions stay in authorised desks.",
        "Not the full 35-step scenario; executable recovery is unavailable.",
        "Virtual time is demonstration timing only. Business and permission time remain real.",
    ],
}


def catalog(db, ctx):
    require(db, ctx.user, ctx.org_id, "demo.read")
    return {"scenarios": [{**CATALOG, "scenario_manifest_hash": digest(CATALOG)}]}


def access(db, ctx, ident, permission="demo.read", mutable=False):
    require(db, ctx.user, ctx.org_id, permission)
    row = exists(db, Workspace, ident)
    if row.owner_user_id != ctx.user.id or row.owner_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Demonstration workspace not found.", status=404)
    if mutable:
        if row.state != "OPEN":
            fail(
                "DEMO_WORKSPACE_SEALED",
                "Create a successor instead of rewriting demonstration history.",
            )
        if ctx.if_match != f'"{row.row_version}"':
            fail("MANIFEST_CHANGED", "Reload this demo workspace ETag.", status=412)
    return row


def create(db, ctx, ident, payload, predecessor=None):
    require(db, ctx.user, ctx.org_id, "demo.workspace.create")
    scenario = db.scalar(
        select(Scenario).where(
            Scenario.scenario_code == payload.scenario_code, Scenario.version == "1"
        )
    )
    if not scenario:
        scenario = Scenario(
            scenario_code=payload.scenario_code,
            version="1",
            scenario_json=CATALOG,
            content_hash=digest(CATALOG),
            created_by_user_id=ctx.user.id,
        )
        db.add(scenario)
        db.flush()
    row = Workspace(
        scenario_revision_id=scenario.id,
        owner_user_id=ctx.user.id,
        owner_organisation_id=ctx.org_id,
        predecessor_workspace_id=predecessor,
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    db.add(Clock(workspace_id=row.id, virtual_as_of=instant(db)))
    db.flush()
    return read(db, ctx, row.id)


def read(db, ctx, ident):
    row = access(db, ctx, ident)
    clock = exists(db, Clock, row.id)
    scenario = exists(db, Scenario, row.scenario_revision_id)
    return {
        "id": row.id,
        "trade_id": row.trade_id,
        "execution_mode": "SIMULATION",
        "state": row.state,
        "etag": f'"{row.row_version}"',
        "scenario_manifest_hash": scenario.content_hash,
        "virtual_as_of": aware(clock.virtual_as_of).isoformat(),
        "business_clock": "REAL_SERVER_TIME",
        "limitations": scenario.scenario_json["limitations"],
        "scenario": scenario.scenario_json,
        "predecessor_workspace_id": row.predecessor_workspace_id,
    }


def advance(db, ctx, ident, payload):
    row = access(db, ctx, ident, "demo.clock.advance", True)
    clock = exists(db, Clock, row.id)
    before = aware(clock.virtual_as_of)
    clock.virtual_as_of = before + timedelta(seconds=payload.advance_seconds)
    clock.row_version += 1
    row.row_version += 1
    value = {
        "from": before.isoformat(),
        "to": clock.virtual_as_of.isoformat(),
        "reason": payload.reason,
        "business_time_changed": False,
    }
    db.add(
        ClockEvent(
            workspace_id=row.id,
            event_json=value,
            content_hash=digest(value),
            created_by_user_id=ctx.user.id,
        )
    )
    return read(db, ctx, ident)


def reset(db, ctx, ident, payload):
    row = access(db, ctx, ident, "demo.workspace.create", True)
    row.state, row.row_version = "SEALED", row.row_version + 1
    # Normal records are preserved, never deleted or secretly reseeded to accepted state.
    return create(db, ctx, None, payload, predecessor=row.id)


def start(db, ctx, ident, payload):
    row = access(db, ctx, ident, "demo.run", True)
    scenario = exists(db, Scenario, row.scenario_revision_id)
    if scenario.content_hash != payload.scenario_manifest_hash:
        fail("MANIFEST_CHANGED", "Use this published scenario's exact hash.", status=412)
    active = db.scalar(
        select(DemoRun.id).where(DemoRun.workspace_id == row.id, DemoRun.status == "RUNNING")
    )
    if active:
        fail("DEMO_RUN_ACTIVE", "Finish or cancel the active run first.")
    run = DemoRun(workspace_id=row.id, created_by=ctx.user.id)
    db.add(run)
    db.flush()
    return run_view(db, ctx, run.id)


def run_access(db, ctx, ident):
    run = exists(db, DemoRun, ident)
    return run, access(db, ctx, run.workspace_id, "demo.run")


def run_view(db, ctx, ident):
    run, row = run_access(db, ctx, ident)
    return {
        "id": run.id,
        "workspace_id": row.id,
        "workspace_etag": f'"{row.row_version}"',
        "trade_id": row.trade_id,
        "status": run.status,
        "etag": f'"{run.row_version}"',
        "current_step_code": run.current_step_code,
        "receipts": [
            {
                "id": r.id,
                "step_code": r.step_code,
                "principal_user_id": r.principal_user_id,
                "receipt": r.receipt_json,
            }
            for r in db.scalars(
                select(StepReceipt)
                .where(StepReceipt.run_id == run.id)
                .order_by(StepReceipt.created_at, StepReceipt.id)
            )
        ],
    }


def step(db, ctx, ident, payload):
    run, row = run_access(db, ctx, ident)
    if row.state != "OPEN" or run.status != "RUNNING" or ctx.if_match != f'"{run.row_version}"':
        fail("MANIFEST_CHANGED", "Run changed or workspace is sealed.", status=412)
    previous = list(db.scalars(select(StepReceipt.step_code).where(StepReceipt.run_id == run.id)))
    codes = [item["step_code"] for item in CATALOG["steps"]]
    if len(previous) >= len(codes) or payload.step_code != codes[len(previous)]:
        fail("DEMO_STEP_ORDER", "Execute the next registered step; clients cannot skip assertions.")
    value = {
        "operation_id": payload.step_code,
        "actor_user_id": ctx.user.id,
        "status": "PASS",
        "business_effects": [],
    }
    if payload.step_code == "CREATE_SIMULATION_DRAFT":
        if row.trade_id:
            fail("DEMO_RESOURCE_EXISTS", "Reset into a successor for a fresh draft.")
        result = create_trade(
            db, ctx, TradeCreate(initiated_by_role="SELLER"), execution_mode="SIMULATION"
        )
        row.trade_id = result["trade_id"]
        row.row_version += 1
        value["business_effects"] = [{"operation_id": "CREATE_TRADE", "trade_id": row.trade_id}]
        created_trade = exists(db, Trade, row.trade_id)
        assertions = {
            "agreement_status": created_trade.agreement_status,
            "execution_mode": created_trade.execution_mode,
            "approved_by_fixture_installer": False,
        }
        if (
            created_trade.agreement_status != "DRAFT"
            or created_trade.execution_mode != "SIMULATION"
        ):
            value["status"], run.status = "UNEXPECTED_FAILURE", "FAILED"
    elif payload.step_code == "READ_INDEPENDENT_DIMENSIONS":
        result = workspace.read(db, ctx, row.trade_id)
        assertions = {
            "schema_code": result["schema_code"],
            "agreement_status": result["commercial"]["agreement_status"],
            "has_global_completion_percent": "completed_percent" in result,
            "bank_settlement_claimed": False,
        }
    else:
        assertions = {"recovery_executable": False, "reason": "EXECUTABLE_RECOVERY_NOT_IMPLEMENTED"}
        value["status"], run.status = "BLOCKED", "BLOCKED"
    run.current_step_code, run.row_version = payload.step_code, run.row_version + 1
    receipt = StepReceipt(
        run_id=run.id,
        step_code=payload.step_code,
        principal_user_id=ctx.user.id,
        receipt_json=value,
        content_hash=digest(value),
        created_by_user_id=ctx.user.id,
    )
    db.add(receipt)
    db.flush()
    db.add(
        Checkpoint(
            step_receipt_id=receipt.id,
            assertion_json=assertions,
            content_hash=digest(assertions),
            created_by_user_id=ctx.user.id,
        )
    )
    return run_view(db, ctx, ident)


def cancel(db, ctx, ident, payload):
    run, row = run_access(db, ctx, ident)
    if row.state != "OPEN":
        fail("DEMO_WORKSPACE_SEALED", "Sealed demonstration runs are read-only.")
    if run.status != "RUNNING" or ctx.if_match != f'"{run.row_version}"':
        fail("MANIFEST_CHANGED", "Run changed or finished.", status=412)
    run.status, run.row_version = "CANCELLED", run.row_version + 1
    return run_view(db, ctx, ident)


def measure(db, ctx, ident, payload):
    run, row = run_access(db, ctx, ident)
    if row.state != "OPEN":
        fail("DEMO_WORKSPACE_SEALED", "Sealed demonstration runs are read-only.")
    value = {
        "measurement_code": payload.measurement_code,
        "provenance": "DEMONSTRATION_TIMING",
        "elapsed_seconds": str((instant(db) - aware(run.created_at)).total_seconds()),
        "operational_time_saved": None,
        "realised_savings_minor": None,
        "limitations": [
            "Script/session elapsed time is not real shipment time or a productivity claim."
        ],
    }
    row = Measurement(
        run_id=run.id,
        measurement_json=value,
        content_hash=digest(value),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    return {"id": row.id, **value}
