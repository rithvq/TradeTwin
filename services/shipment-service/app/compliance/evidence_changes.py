"""Prove evidence changes without returning query witnesses, identities or source payloads."""

from sqlalchemy import select

from app.document_desk import access as document_access
from app.document_desk.models import Document, VerificationCheck, VerificationResult
from app.trades.errors import TradeError
from app.trades.terms import digest

from . import context, governance, lineage, public_records, rule_dependencies
from .models import Evaluation
from .models_dashboard import EvidenceChangeBaseline

COMPONENTS = {
    "documents": "SOURCE_DOCUMENT_CHANGED",
    "verification_results": "VERIFICATION_RESULTS_CHANGED",
    "trusted_keys": "VERIFICATION_TRUST_CHANGED",
    "assignment": "ASSIGNMENT_CHANGED",
    "current_vehicle": "VEHICLE_CHANGED",
    "manifest": "LOADING_MANIFEST_CHANGED",
    "fact": "DECLARED_FACTS_CHANGED",
    "binding": "EVIDENCE_BINDING_CHANGED",
    "turnover": "EVIDENCE_INPUTS_CHANGED",
    "registry_manifest": "RULE_REGISTRY_CHANGED",
    "corridor_intelligence": "CORRIDOR_CHANGED",
    "holds": "INTEGRITY_HOLD_CHANGED",
}


def queries(capture):
    return {
        kind: {"matches": len(query["matching_revisions"]), "digest": digest(query)}
        for kind, query in capture.get("queries", {}).items()
    }


def retain(db, ctx, evaluation, bundle):
    snapshot = bundle["snapshot"]
    captured = queries(snapshot.get("lineage", {}))
    previous = db.scalar(
        select(EvidenceChangeBaseline)
        .join(Evaluation, Evaluation.id == EvidenceChangeBaseline.evaluation_id)
        .where(
            Evaluation.consignment_id == evaluation.consignment_id,
            Evaluation.action == evaluation.action,
            Evaluation.execution_mode == evaluation.execution_mode,
            Evaluation.id != evaluation.id,
        )
        .order_by(EvidenceChangeBaseline.created_at.desc(), EvidenceChangeBaseline.id.desc())
        .limit(1)
    )
    old = (
        previous.summary_json.get("queries", {})
        if previous and digest(previous.summary_json) == previous.content_hash
        else {}
    )
    summary = {
        "schema": "EVIDENCE_CHANGE_BASELINE_V1",
        "queries": captured,
        "query_capture_recorded": "lineage" in snapshot,
        "components": {key: digest(snapshot["context"].get(key)) for key in COMPONENTS},
        "engine_digest": bundle["manifest_hash"],
        "previous_evaluation_id": previous.evaluation_id if previous else None,
        "empty_searches_gaining_matches": [
            kind
            for kind, value in captured.items()
            if kind in old and old[kind]["matches"] == 0 and value["matches"] > 0
        ],
    }
    db.add(
        EvidenceChangeBaseline(
            evaluation_id=evaluation.id,
            summary_json=summary,
            content_hash=digest(summary),
            created_by_user_id=ctx.user.id,
        )
    )


def visible_match(db, ctx, trade, kind):
    # Existence in a private query is never itself permission to disclose a match.
    for doc in db.scalars(
        select(Document).where(Document.trade_id == trade.id, Document.document_type == kind)
    ):
        try:
            document_access.document(db, ctx, doc.id)
            if not doc.current_version_id or public_records.readable_version(
                db, ctx, doc.current_version_id
            ):
                return True
        except TradeError:
            continue
    return False


def adverse_change(db, ctx, evaluation, current):
    previous = {r["id"] for r in evaluation.snapshot_json.get("verification_results", [])}
    for observed in current.get("verification_results", []):
        if observed["id"] in previous:
            continue
        result = db.get(VerificationResult, observed["id"])
        check = db.get(VerificationCheck, result.verification_check_id) if result else None
        if not check or not public_records.readable_version(db, ctx, check.document_version_id):
            continue
        data = result.result_json
        if (
            data.get("normalised_result", {}).get("status")
            in {"CANCELLED", "EXPIRED", "INACTIVE", "REVOKED", "INVALID"}
            or data.get("signature_integrity") == "INVALID"
        ):
            return True
    return False


def read(db, ctx, evaluation, trade, cn, freshness, at):
    baseline = db.scalar(
        select(EvidenceChangeBaseline).where(EvidenceChangeBaseline.evaluation_id == evaluation.id)
    )
    value = {
        "status": freshness,
        "detail_status": "NOT_RECORDED",
        "reason_codes": [],
        "transitions": [],
        "notice": "Detail not recorded.",
    }
    if not baseline:
        return value
    saved = baseline.summary_json
    if digest(saved) != baseline.content_hash:
        return {**value, "detail_status": "UNAVAILABLE", "notice": "Detail unavailable."}
    _, registry, _ = governance.resolve(db, trade.execution_mode, at)
    current, _ = context.dependency_snapshot(db, trade, cn, registry, assessment_time=at)
    reasons = {
        code
        for key, code in COMPONENTS.items()
        if saved["components"][key] != digest(current.get(key))
    }
    if saved["engine_digest"] != digest(rule_dependencies.engine_manifest()):
        reasons.add("ENGINE_VERSION_CHANGED")
    if adverse_change(db, ctx, evaluation, current):
        reasons.add("NEW_ADVERSE_VERIFICATION_RESULT")
    transitions = []
    if saved["query_capture_recorded"]:
        current_queries = queries(lineage.capture(db, trade))
        for kind, old in saved["queries"].items():
            new = current_queries.get(kind)
            if new and old["digest"] != new["digest"]:
                reasons.add("EVIDENCE_SEARCH_CHANGED")
                if old["matches"] == 0 < new["matches"] and visible_match(db, ctx, trade, kind):
                    transitions.append(
                        {
                            "document_type": kind,
                            "basis": "SINCE_EVALUATION",
                            "code": "EMPTY_SEARCH_GAINED_MATCH",
                        }
                    )
        for kind in saved["empty_searches_gaining_matches"]:
            if visible_match(db, ctx, trade, kind):
                transitions.append(
                    {
                        "document_type": kind,
                        "basis": "BETWEEN_EVALUATIONS",
                        "code": "EMPTY_SEARCH_GAINED_MATCH",
                    }
                )
    value.update(
        detail_status="RECORDED",
        reason_codes=sorted(reasons),
        transitions=transitions,
        notice="A search match is not accepted evidence. Review and exact binding are required.",
    )
    return value
