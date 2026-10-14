"""Historical replay is read-only and never reinterprets current state as past evidence."""

from copy import deepcopy

from sqlalchemy import func, select

from app.compliance.clock import aware, instant
from app.compliance.ledger import record
from app.compliance.models import Authorization, Evaluation
from app.corridor.models import Assessment, RecoveryCase
from app.document_desk.models import Job, Outbox
from app.freight import views
from app.freight.access import price_access
from app.freight.compute import captured_result, engine_manifest
from app.freight.models import Commitment, Run
from app.operations.access import consignment, exists, fail
from app.trades.access import require
from app.trades.models import uid
from app.trades.terms import digest

from .models import Comparison, ReplayRequest, ReplayResult

MODELS = {
    "TRADETWIN_RUN": Run,
    "DISPATCH_AUTHORISATION": Authorization,
    "RECOVERY_CASE": RecoveryCase,
    "FREIGHT_COMMITMENT": Commitment,
}


def subject(db, ctx, kind, ident, permission="evidence.replay.request"):
    row = exists(db, MODELS[kind], ident)
    require(db, ctx.user, ctx.org_id, permission, row.trade_id)
    trade, _, _ = consignment(db, ctx, row.consignment_id, "consignment.read")
    if kind == "TRADETWIN_RUN":
        views.planning(db, ctx, row.consignment_id)
    elif kind == "FREIGHT_COMMITMENT":
        views.commitment_view(db, ctx, row.id)
    else:
        require(db, ctx.user, ctx.org_id, "compliance.read", trade.id)
    return row, trade


def identity(db, row, kind):
    if kind == "TRADETWIN_RUN":
        return row.content_hash, row.engine_version, row.evaluated_as_of
    if kind == "FREIGHT_COMMITMENT":
        return row.content_hash, "FREIGHT_COMMITMENT_V1", row.created_at
    if kind == "DISPATCH_AUTHORISATION":
        evaluation = exists(db, Evaluation, row.evaluation_id)
        return (
            evaluation.dependency_hash,
            evaluation.engine_version,
            evaluation.evaluated_at or evaluation.created_at,
        )
    assessment = exists(db, Assessment, row.assessment_id)
    return (
        assessment.content_hash,
        assessment.result_json["engine_version"],
        assessment.evaluated_as_of,
    )


def request(db, ctx, ident, payload):
    row, trade = subject(db, ctx, payload.subject_type, payload.subject_id)
    fingerprint, engine, _ = identity(db, row, payload.subject_type)
    if payload.source_manifest_hash != fingerprint:
        fail("MANIFEST_CHANGED", "Use the exact retained source manifest hash.", status=412)
    count = db.scalar(
        select(func.count())
        .select_from(ReplayRequest)
        .where(
            ReplayRequest.requested_by_user_id == ctx.user.id,
            ReplayRequest.job_state.in_(["QUEUED", "RUNNING"]),
        )
    )
    if count >= 2:
        fail("JOB_RATE_LIMITED", "Finish an outstanding replay first.", status=429)
    request = ReplayRequest(
        id=uid(),
        trade_id=trade.id,
        subject_type=payload.subject_type,
        subject_id=row.id,
        replay_kind=payload.replay_kind,
        source_manifest_hash=fingerprint,
        expected_engine_version=payload.expected_engine_version,
        requested_by_user_id=ctx.user.id,
        requested_by_organisation_id=ctx.org_id,
        created_by=ctx.user.id,
    )
    db.add(request)
    db.flush()
    job = Job(
        trade_id=trade.id,
        stage="DECISION_REPLAY",
        input_fingerprint=digest({"request_id": request.id, "manifest": fingerprint}),
        pipeline_version="DECISION_REPLAY_1",
        schema_version="DECISION_REPLAY_REQUEST_V1",
        configuration_hash=digest({"engine": engine}),
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json={"replay_request_id": request.id},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    request.job_id = job.id
    db.add(Outbox(job_id=job.id))
    record(db, ctx, "DECISION_REPLAY_QUEUED", request)
    return {
        "id": request.id,
        "job_state": "QUEUED",
        "source_manifest_hash": fingerprint,
        "engine_version": engine,
    }


def complete(db, ctx, ident):
    requested = exists(db, ReplayRequest, ident)
    row, trade = subject(db, ctx, requested.subject_type, requested.subject_id)
    previous = db.scalar(select(ReplayResult).where(ReplayResult.request_id == requested.id))
    if previous:
        return previous
    fingerprint, engine, as_of = identity(db, row, requested.subject_type)
    integrity = "PASS" if fingerprint == requested.source_manifest_hash else "FAIL"
    outcome, differences = "NOT_REQUESTED", []
    limitations = [
        "Historical decision only; creates no booking, approval, payment or movement permission.",
        "Content hashes establish retained-data integrity, not source truth.",
    ]
    if requested.subject_type == "TRADETWIN_RUN":
        integrity = (
            "PASS"
            if digest(row.input_json) == row.content_hash
            and row.result_json
            and digest(row.result_json) == row.result_hash
            else "FAIL"
        )
    elif requested.subject_type == "FREIGHT_COMMITMENT":
        integrity = "PASS" if digest(row.commitment_json) == fingerprint else "FAIL"
    elif requested.subject_type == "RECOVERY_CASE":
        assessment = exists(db, Assessment, row.assessment_id)
        integrity = (
            "PASS"
            if digest({"input": assessment.input_json, "result": assessment.result_json})
            == fingerprint
            else "FAIL"
        )
    else:
        evaluation = exists(db, Evaluation, row.evaluation_id)
        integrity = "PASS" if digest(evaluation.snapshot_json) == fingerprint else "INCOMPLETE"
    if requested.replay_kind == "RECOMPUTE_CAPTURED_INPUTS":
        if engine != requested.expected_engine_version:
            outcome = "UNSUPPORTED_ENGINE"
        elif integrity != "PASS":
            outcome = "INCOMPLETE_INPUTS"
        elif requested.subject_type != "TRADETWIN_RUN":
            outcome = "UNSUPPORTED_ENGINE"
            limitations.append(
                "No compatible captured-input recomputation engine registered for this subject."
            )
        elif not row.input_json.get("sources") or not row.input_json.get("scenarios"):
            outcome = "INCOMPLETE_INPUTS"
        elif row.input_json.get("engine_manifest") != engine_manifest():
            outcome = "UNSUPPORTED_ENGINE"
            limitations.append(
                "A different code/dependency manifest cannot run as the current engine."
            )
        else:
            try:
                recomputed = captured_result(
                    deepcopy(row.input_json), row.content_hash, row.execution_mode
                )
                original = {k: row.result_json[k] for k in ["candidates", "rankings"]}
                differences = diff(original, recomputed)
                outcome = "MISMATCH" if differences else "MATCH"
            except (KeyError, ValueError, TypeError):
                outcome = "INCOMPLETE_INPUTS"
    value = {
        "schema_version": 1,
        "request_id": requested.id,
        "subject_reference": {"subject_type": requested.subject_type, "subject_id": row.id},
        "original_business_as_of": aware(as_of).isoformat(),
        "original_recorded_at": aware(row.created_at).isoformat(),
        "source_manifest_hash": fingerprint,
        "engine_version": engine,
        "input_integrity": integrity,
        "recomputation": outcome,
        "differences": differences,
        "unavailable_source_references": [],
        "redacted_dependency_count": 0,
        "limitations": limitations,
        "current_readiness": "NOT_ASSESSED_BY_REPLAY",
        "completed_at": instant(db).isoformat(),
    }
    result = ReplayResult(
        request_id=requested.id,
        result_json=value,
        result_hash=digest(value),
        completed_at=instant(db),
    )
    db.add(result)
    requested.job_state = "COMPLETED"
    return result


def diff(left, right, path="", budget=200):
    output = []
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            output.extend(
                diff(left.get(key), right.get(key), path + "/" + key, budget - len(output))
            )
            if len(output) >= budget:
                break
    elif isinstance(left, list) and isinstance(right, list):
        for index in range(max(len(left), len(right))):
            output.extend(
                diff(
                    left[index] if index < len(left) else None,
                    right[index] if index < len(right) else None,
                    path + f"/{index}",
                    budget - len(output),
                )
            )
            if len(output) >= budget:
                break
    elif left != right and budget > 0:
        output.append(
            {
                "path": path,
                "original_value": left,
                "recomputed_value": right,
                "reason": "Recorded values differ; no unsupported causal inference.",
            }
        )
    return output[: max(0, budget)]


def read(db, ctx, ident):
    requested = exists(db, ReplayRequest, ident)
    row, trade = subject(db, ctx, requested.subject_type, requested.subject_id)
    if (
        requested.requested_by_user_id != ctx.user.id
        or requested.requested_by_organisation_id != ctx.org_id
    ):
        fail("NOT_FOUND", "Replay request not found for this recipient.", status=404)
    result = db.scalar(select(ReplayResult).where(ReplayResult.request_id == requested.id))
    if not result:
        return {"id": requested.id, "job_state": requested.job_state}
    if digest(result.result_json) != result.result_hash:
        fail("EVIDENCE_INTEGRITY_FAILED", "Retained replay integrity check failed.")
    value = deepcopy(result.result_json)
    if requested.subject_type == "TRADETWIN_RUN" and not price_access(db, ctx, trade):
        value["redacted_dependency_count"] = len(value["differences"])
        value["differences"] = []
        value["limitations"].append(
            "Private comparison differences are withheld, not replaced with hashes."
        )
    return {
        **value,
        "id": requested.id,
        "result_hash": result.result_hash,
        "job_state": requested.job_state,
        "recorded_decision": projection(db, ctx, requested.subject_type, row),
    }


def projection(db, ctx, kind, row):
    if kind == "TRADETWIN_RUN":
        value = views.run_view(db, ctx, row.id)
        for key in ["freshness", "permitted_next_actions", "freshness_at_completion"]:
            value.pop(key, None)
        value["current_readiness"] = "NOT_ASSESSED_BY_REPLAY"
        return value
    if kind == "FREIGHT_COMMITMENT":
        value = views.commitment_view(db, ctx, row.id)
        value.pop("events", None)
        value["current_readiness"] = "NOT_ASSESSED_BY_REPLAY"
        return value
    if kind == "DISPATCH_AUTHORISATION":
        from app.compliance.handoff import evidence

        value = evidence(db, ctx, row.id, authorization=True)
        for key in ("freshness", "manifest_hash", "decision_manifest_hash", "decision_manifest"):
            value.pop(key, None)
        if value.get("dispatch"):
            value["dispatch"].pop("effective_state", None)
            value["dispatch"].pop("consumed_event_id", None)
        value["current_readiness"] = "NOT_ASSESSED_BY_REPLAY"
        return value
    assessment = exists(db, Assessment, row.assessment_id)
    from app.corridor.service import event_visible

    retained = deepcopy(assessment.result_json)
    allowed = {
        e["id"] for e in assessment.input_json.get("events", []) if event_visible(db, ctx, e)
    }
    retained["items"] = [
        i
        if i["event_revision_id"] in allowed
        else {
            "outcome": i["outcome"],
            "edge_key": i["edge_key"],
            "limitations": ["Restricted source evidence."],
        }
        for i in retained.get("items", [])
    ]
    return {
        "id": row.id,
        "assessment_id": assessment.id,
        "recorded_assessment": retained,
        "evaluated_as_of": aware(assessment.evaluated_as_of).isoformat(),
        "current_readiness": "NOT_ASSESSED_BY_REPLAY",
    }


def comparison(db, ctx, ident, payload):
    left, trade = subject(
        db,
        ctx,
        payload.left_subject_reference.subject_type,
        payload.left_subject_reference.subject_id,
    )
    right, other = subject(
        db,
        ctx,
        payload.right_subject_reference.subject_type,
        payload.right_subject_reference.subject_id,
    )
    if trade.id != other.id or left.consignment_id != right.consignment_id:
        fail(
            "WORKSPACE_ACCESS_DENIED",
            "Compare decisions for the same trade and consignment.",
            status=422,
        )
    records, refs = [], []
    for row, reference, expected in zip(
        [left, right],
        [payload.left_subject_reference, payload.right_subject_reference],
        payload.expected_manifest_hashes,
        strict=True,
    ):
        fingerprint, engine, as_of = identity(db, row, reference.subject_type)
        if expected != fingerprint:
            fail("MANIFEST_CHANGED", "Comparison source manifest changed.", status=412)
        records.append(projection(db, ctx, reference.subject_type, row))
        refs.append(
            {
                "subject_type": reference.subject_type,
                "subject_id": row.id,
                "as_of": aware(as_of).isoformat(),
                "engine_version": engine,
            }
        )
    value = {
        "left_subject_reference": refs[0],
        "right_subject_reference": refs[1],
        "common_subject_scope": {"trade_id": trade.id, "consignment_id": left.consignment_id},
        "explanation_items": diff(records[0], records[1]),
        "limitations": [
            "Permission-filtered values; changes are not presumed savings or legal clearance."
        ],
    }
    # A comparison retains only the recipient-filtered result, never raw private source snapshots.
    pending = []
    for row, reference, expected in zip(
        [left, right],
        [payload.left_subject_reference, payload.right_subject_reference],
        payload.expected_manifest_hashes,
        strict=True,
    ):
        request_row = ReplayRequest(
            trade_id=trade.id,
            subject_type=reference.subject_type,
            subject_id=row.id,
            replay_kind="RECORDED_DECISION",
            source_manifest_hash=expected,
            expected_engine_version=identity(db, row, reference.subject_type)[1],
            requested_by_user_id=ctx.user.id,
            requested_by_organisation_id=ctx.org_id,
            job_state="COMPLETED",
            created_by=ctx.user.id,
        )
        db.add(request_row)
        pending.append(request_row)
    db.flush()
    for requested in pending:
        complete(db, ctx, requested.id)
    result = Comparison(
        trade_id=trade.id,
        left_request_id=pending[0].id,
        right_request_id=pending[1].id,
        comparison_json=value,
        content_hash=digest(value),
        created_by_user_id=ctx.user.id,
    )
    db.add(result)
    record(db, ctx, "DECISION_COMPARISON_RECORDED", result)
    return {"id": result.id, "result_url": f"/api/v1/evidence/comparisons/{result.id}"}
