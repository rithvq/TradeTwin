"""Pure reference evaluator: captured inputs and time only, no persistence or ambient clock."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .expression import evaluate

LIMITATIONS = [
    "Platform dispatch authorisation is not government clearance.",
    "No tax rates, classification, route, freight price or government registration is certified.",
]


def timestamp(value):
    try:
        result = datetime.fromisoformat(value) if value else None
        return result.replace(tzinfo=UTC) if result and result.tzinfo is None else result
    except (ValueError, TypeError):
        return None


def profile_supported(data, policy):
    facts = data["facts"]
    corridor = [
        data["inherited"]["origin_state_code"],
        *(facts.get("declared_transit_state_codes") or []),
        data["inherited"]["destination_state_code"],
    ]
    known = (
        facts.get("scope_profile_code") is not None
        and bool(facts.get("commodity_scope_codes"))
        and facts.get("declared_transit_state_codes") is not None
    )
    return known, bool(
        known
        and facts["scope_profile_code"] in policy["supported_scope_codes"]
        and set(facts["commodity_scope_codes"]) <= set(policy["supported_commodity_codes"])
        and corridor in policy["supported_corridors"]
    )


def prepared_data(snapshot):
    data = deepcopy(snapshot.get("data", {}))
    if not snapshot.get("pack"):
        return data, None, None, False, False
    pack = snapshot["pack"]
    scope = evaluate(pack["supported_scope"], data)
    excluded = evaluate(pack["excluded_scope"], data)
    known, supported = profile_supported(data, pack["policy"])
    supported = supported and snapshot["plan_valid"]
    data["proof"]["scope_supported"] = (
        None
        if not known or scope is None or excluded is None
        else scope is True and excluded is False and supported
    )
    if not snapshot["recipient_current"]:
        data["proof"]["scope_supported"] = False
        data["diagnostics"]["SUPPORTED_SCOPE"] = {
            "recipient_confirmation": "CONFLICT_WITH_ACCEPTED_SNAPSHOT",
            "corrective_action": "Buyer correction or accepted commercial amendment required",
        }
    return data, scope, excluded, known, supported


def rule_time(definition, data, dimensions, at):
    start, end = (
        timestamp(definition["effective_from"]),
        timestamp(definition.get("effective_until")),
    )
    basis = at
    if definition["date_basis"] == "INVOICE_DATE":
        day = data["invoice"].get("issue_date")
        basis = (
            datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("Asia/Kolkata")) if day else None
        )
    elif definition["date_basis"] == "PLANNED_ARRIVAL_TIME":
        basis = timestamp(data["facts"].get("expected_arrival_at"))
    elif definition["date_basis"] == "OBSERVATION_TIME":
        times = [
            timestamp(d.get("provider_observed_at") or d.get("checked_at"))
            for d in dimensions
            if d.get("selected") and d.get("check_type") == definition.get("observation_check_type")
        ]
        positions = [start <= t and (end is None or t < end) for t in times if t]
        basis = (
            times[0] if times and all(times) and (all(positions) or not any(positions)) else None
        )
    deadlines = (
        [value for value in (start, end) if value and value > at]
        if definition["date_basis"] == "ACTION_TIME"
        else []
    )
    return basis, start, end, deadlines


def calculate_rule(rule, data, dimensions, at):
    definition = rule["definition"]
    basis, start, end, _ = rule_time(definition, data, dimensions, at)
    applicable = evaluate(definition["applicability_expression"], data)
    if basis is None:
        applicable = None
    elif basis < start or (end and basis >= end):
        applicable = False
    satisfied = (
        evaluate(definition["satisfaction_expression"], data) if applicable is True else None
    )
    return {
        "applicability": "APPLICABLE"
        if applicable is True
        else "NOT_APPLICABLE"
        if applicable is False
        else "UNKNOWN",
        "outcome": "NOT_APPLICABLE"
        if applicable is False
        else "UNKNOWN"
        if applicable is None or satisfied is None
        else "SATISFIED"
        if satisfied is True
        else "FAILED",
        "predicate_result": satisfied,
        "comparison": deepcopy(data.get("diagnostics", {}).get(definition["requirement_code"], {})),
    }


def requirement(rule, kernel, data, dimensions, at, evidence_refs):
    definition = rule["definition"]
    basis, _, _, _ = rule_time(definition, data, dimensions, at)
    return {
        "rule_id": rule["id"],
        "requirement_code": rule["requirement_code"],
        "rule_class": rule["rule_class"],
        "applicability": kernel["applicability"],
        "outcome": kernel["outcome"],
        "mandatory": definition["mandatory"],
        "severity": definition["severity"],
        "expected_json": {
            "required_evidence_types": definition["required_evidence_types"],
            "date_basis": definition["date_basis"],
            "date_basis_timestamp": basis.isoformat() if basis else None,
        },
        "observed_json": {
            "predicate_result": kernel["predicate_result"],
            "comparison": deepcopy(kernel["comparison"]),
            "correction_links": [
                {
                    "document_version_id": ref["document_version_id"],
                    "url": f"/documents/versions/{ref['document_version_id']}/review",
                }
                for ref in (
                    [
                        data["binding"]["movement_document"],
                        *data["binding"].get("supporting_documents", []),
                    ]
                    if data.get("binding")
                    else []
                )
            ],
        },
        "evidence_refs_json": deepcopy(evidence_refs),
        "source_ids": definition["source_ids"],
        "explanation": definition["explanation_template"],
        "remedies_json": definition["remedy_codes"],
    }


def calculate_full(snapshot, rules, assessment_time, kernels=None):
    """Validated kernels replace rule arithmetic, never safety checks or output assembly."""
    at = assessment_time
    deadline = at + timedelta(seconds=900)
    result = {
        "job_state": "COMPLETED",
        "decision": "UNSUPPORTED",
        "coverage": {},
        "limitations": list(LIMITATIONS),
        "requirements": [],
        "kernels": {},
    }
    if snapshot["stale"]:
        result.update(job_state="COMPLETED_STALE", decision="BLOCKED")
        result["limitations"].append(
            "Inputs changed while this evaluation was queued. Submit a fresh evaluation."
        )
    elif not snapshot.get("pack"):
        result["limitations"].append(
            "Exactly one effective independently published pack is required; "
            "absent, suspended or overlapping packs cannot authorise dispatch."
        )
    else:
        pack = snapshot["pack"]
        data, scope, excluded, known, supported = prepared_data(snapshot)
        result["coverage"] = {
            **deepcopy(pack["coverage"]),
            "scope_predicate": scope,
            "scope_profile_supported": supported,
            "independent_verification_dimensions": deepcopy(snapshot["dimensions"]),
            "authority_deadlines": deepcopy(data.get("authority_deadlines", [])),
        }
        result["limitations"] += pack["limitations"]
        deadlines = [timestamp(value) for value in snapshot["deadlines"]]
        for rule in rules:
            kernel = (
                deepcopy(kernels[rule["id"]])
                if kernels is not None and rule["id"] in kernels
                else calculate_rule(rule, data, snapshot["dimensions"], at)
            )
            result["kernels"][rule["id"]] = kernel
            result["requirements"].append(
                requirement(
                    rule, kernel, data, snapshot["dimensions"], at, snapshot["evidence_refs"]
                )
            )
            deadlines += rule_time(rule["definition"], data, snapshot["dimensions"], at)[3]
        rows, ctx = result["requirements"], snapshot["context"]
        sources = snapshot["source_state"]
        blocked_source = bool(
            sources["open_conflicts"] or sources["non_governing_sources"]
        ) or not all(s["clean"] for s in sources["sources"])
        blocked_source = blocked_source or not all(
            d["reference"]["document_version_id"] == d["current_version_id"]
            and d["reference"]["reviewed_fact_revision_id"] == d["effective_fact_revision_id"]
            and d["lifecycle_status"] == "ACTIVE"
            and all(
                a["security_state"] == "CLEAN" and a["hash"] == a["current_hash"]
                for a in d["assets"]
            )
            for d in ctx["documents"]
        )
        missing = (
            not known
            or scope is None
            or excluded is None
            or not snapshot["binding_revision_id"]
            or not snapshot["loading_manifest_revision_id"]
        )
        operational_block = (
            (ctx.get("corridor_intelligence") or {}).get("outcome") in {"BLOCKED", "NEEDS_REVIEW"}
            or not snapshot["recipient_current"]
            or ctx["consignment"]["planning_status"] != "PREPARING"
            or ctx["consignment"]["revision_alignment"] != "CURRENT"
            or ctx["consignment"]["movement_status"]
            != ("NOT_STARTED" if snapshot["action"] == "PICKUP_CONFIRMED" else "PICKED_UP")
            or any(h["active"] for h in ctx["holds"])
            or not (ctx.get("current_vehicle") or {}).get("active", False)
            or (ctx.get("current_vehicle") or {}).get("vehicle")
            != {
                k: v
                for k, v in (ctx.get("assignment") or {}).get("vehicle_snapshot", {}).items()
                if k != "id"
            }
        )
        unsupported_invoice = (
            snapshot["binding_revision_id"] is not None
            and snapshot["whole_invoice_coverage"] is not True
        )
        mandatory_failed = any(
            r["mandatory"] and r["outcome"] in {"FAILED", "UNKNOWN"} for r in rows
        )
        result["decision"] = (
            "UNSUPPORTED"
            if scope is False
            or excluded is True
            or (known and not supported)
            or unsupported_invoice
            else "BLOCKED"
            if blocked_source or mandatory_failed or missing or operational_block
            else "NEEDS_REVIEW"
            if any(r["outcome"] in {"FAILED", "UNKNOWN"} for r in rows)
            else "ELIGIBLE_FOR_REVIEW"
        )
        for condition, message in [
            (
                blocked_source,
                "SOURCE_CONFLICT_UNRESOLVED: source integrity/conflict blocks release.",
            ),
            (
                unsupported_invoice,
                "One complete issued invoice per consignment is required; "
                "Phase 3 split mapping is preserved, not proportionally valued for release.",
            ),
            (
                missing,
                "Mandatory scope facts, loading manifest or exact bindings are missing/unknown.",
            ),
            (
                operational_block,
                "Current movement state, revision alignment or integrity hold blocks this action.",
            ),
            (
                not snapshot["recipient_current"],
                "Recipient confirmation conflicts with the accepted snapshot. "
                "Confirm corrected recipient evidence or amend the agreement.",
            ),
        ]:
            if condition:
                result["limitations"].append(message)
        deadlines.append(
            at + timedelta(seconds=pack["policy"]["default_authorisation_ttl_seconds"])
        )
        if snapshot["registry_boundary"]:
            deadlines.append(timestamp(snapshot["registry_boundary"]))
        deadline = min([deadline, *deadlines])
    corridor_boundary = (snapshot["context"].get("corridor_intelligence") or {}).get("valid_until")
    if corridor_boundary:
        deadline = min(deadline, timestamp(corridor_boundary))
    result["valid_until"] = deadline.isoformat()
    return result
