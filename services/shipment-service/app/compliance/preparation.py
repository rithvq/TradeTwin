"""Database snapshot preparation; full and incremental arithmetic share these inputs."""

from copy import deepcopy

from sqlalchemy import select

from app.freight.commitments import plan_valid

from . import calculation, context, governance, inputs, lineage, public_records, recipient
from .models import Binding, Rule


def prepare_snapshot(db, trade, cn, evaluation, at):
    packs, registry, boundary = governance.resolve(db, trade.execution_mode, at)
    _, fingerprint = context.dependency_snapshot(db, trade, cn, registry, assessment_time=at)
    snapshot = {
        "schema": "COMPLIANCE_CALCULATION_V1",
        "trade_id": trade.id,
        "consignment_id": cn.id,
        "execution_mode": trade.execution_mode,
        "action": evaluation.action,
        "assessment_time": at.isoformat(),
        "stale": fingerprint != evaluation.dependency_hash,
        "context": deepcopy(evaluation.snapshot_json),
        "registry": registry,
        "registry_boundary": boundary.isoformat() if boundary else None,
        "binding_revision_id": evaluation.binding_revision_id,
        "loading_manifest_revision_id": evaluation.loading_manifest_revision_id,
        "pack": None,
        "evidence_refs": public_records.input_references(evaluation.snapshot_json),
    }
    rules = []
    if not snapshot["stale"] and len(packs) == 1:
        pack = packs[0]
        data, deadlines, dimensions = inputs.prepare(db, trade, cn, pack, evaluation.action, at)
        binding = (
            db.get(Binding, evaluation.binding_revision_id)
            if evaluation.binding_revision_id
            else None
        )
        snapshot.update(
            data=deepcopy(data),
            deadlines=[d.isoformat() for d in deadlines],
            dimensions=dimensions,
            plan_valid=bool(
                calculation.profile_supported(data, pack.policy_json)[1]
                and plan_valid(db, trade, cn, data["facts"], at)
            ),
            recipient_current=bool(recipient.compatible(recipient.current(db, cn), trade)),
            whole_invoice_coverage=binding.binding_json.get("whole_invoice_coverage")
            if binding
            else None,
            source_state=governance.sources_current(db, pack),
            pack={
                "id": pack.id,
                "hash": pack.content_hash,
                "supported_scope": pack.supported_scope_json,
                "excluded_scope": pack.excluded_scope_json,
                "coverage": pack.coverage_json,
                "policy": pack.policy_json,
                "limitations": pack.limitations_json,
            },
        )
        rules = [
            {
                "id": rule.id,
                "rule_code": rule.rule_code,
                "version": rule.rule_version,
                "requirement_code": rule.requirement_code,
                "rule_class": rule.rule_class,
                "hash": rule.content_hash,
                "definition": deepcopy(rule.rule_json),
            }
            for rule in db.scalars(
                select(Rule).where(Rule.pack_revision_id == pack.id).order_by(Rule.rule_code)
            )
        ]
        snapshot["lineage"] = lineage.capture(db, trade)
    return snapshot, rules
