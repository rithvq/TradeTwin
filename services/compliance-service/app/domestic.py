"""Domestic document readiness for a bounded, ordinary road-movement rule set."""

from datetime import UTC, datetime

from app.schemas import (
    ComplianceAssessmentResult,
    ComplianceStatus,
    ConsignmentComplianceResult,
    InformationGainQuestionRead,
    RouteOptimizationRead,
    RouteOptionRead,
)


def evaluate_domestic(
    shipment, events, documents, rules, answers, evaluate_rule, aggregate_status, unique_ordered
):
    plan = shipment["domestic"]
    results = []
    registered = answers.get("registered_consignor", plan.get("registered_consignor"))
    ordinary = answers.get("ordinary_goods", plan.get("ordinary_goods"))
    supported = (
        registered in (True, "yes")
        and ordinary in (True, "yes")
        and plan.get("movement_reason") == "SUPPLY"
        and shipment.get("transport_mode") == "ROAD"
    )
    for item in shipment.get("consignments", []):
        detail = item.get("domestic") or {}
        destination = detail.get("destination", {})
        procedure = (
            "interstate" if plan["origin"]["state"] != destination.get("state") else "intrastate"
        )
        matches = []
        if supported:
            for rule in rules:
                if rule.conditions.get("scope") != "india_domestic":
                    continue
                if rule.procedure_type not in ("domestic", procedure):
                    continue
                if rule.jurisdiction not in (
                    "India",
                    destination.get("state"),
                    plan["origin"]["state"],
                ):
                    continue
                minimum = rule.conditions.get("consignment_value_above")
                if minimum is not None and detail.get("consignment_value", 0) <= minimum:
                    continue
                explicit = answers.get(
                    f"eway_bill_required:{item['id']}", detail.get("eway_bill_required")
                )
                if rule.conditions.get("requires_eway_confirmation") and explicit not in (
                    True,
                    "yes",
                ):
                    continue
                event = next(
                    (
                        event
                        for event in reversed(events)
                        if event.get("consignment_id") in (None, item["id"])
                    ),
                    {},
                )
                matches.append(evaluate_rule(rule, item, documents, event.get("id")))
        missing = unique_ordered(doc for result in matches for doc in result.missing_documents)
        actions = unique_ordered(
            result.recommended_action for result in matches if result.recommended_action
        )
        unresolved = []
        if not supported:
            unresolved.append(
                "Confirm registered consignor and ordinary taxable goods supplied by road. "
                "Other movements require a reviewed rule set."
            )
        if procedure == "intrastate":
            explicit = answers.get(
                f"eway_bill_required:{item['id']}", detail.get("eway_bill_required")
            )
            if explicit is None:
                unresolved.append(
                    "Confirm e-way bill applicability using the applicable state notification."
                )
        if not detail:
            unresolved.append(
                "Provide domestic consignment destination and total consignment value."
            )
        if not matches:
            unresolved.append("No applicable domestic rules are available.")
        status = aggregate_status([result.status for result in matches])
        if unresolved and status == ComplianceStatus.COMPLIANT:
            status = ComplianceStatus.INSUFFICIENT_INFORMATION
        results.append(
            ConsignmentComplianceResult(
                consignment_id=item["id"],
                product_name=item["product_name"],
                jurisdiction="India",
                procedure_type=procedure,
                status=status,
                applicable_rules=matches,
                missing_documents=missing,
                violations=[result.violation for result in matches if result.violation],
                recommended_action="; ".join(actions + unresolved)
                or "Documents satisfy the supported domestic checks.",
            )
        )
    return ComplianceAssessmentResult(
        shipment_id=shipment["id"],
        status=aggregate_status([item.status for item in results]),
        applicable_rules=[rule for item in results for rule in item.applicable_rules],
        missing_documents=unique_ordered(doc for item in results for doc in item.missing_documents),
        violations=unique_ordered(value for item in results for value in item.violations),
        recommended_action="; ".join(unique_ordered(item.recommended_action for item in results)),
        consignment_results=results,
    )


def domestic_questions(shipment):
    plan = shipment["domestic"]
    questions = []
    for attribute, question, score in [
        ("registered_consignor", "Is the consignor registered under GST?", 100),
        (
            "ordinary_goods",
            "Is this an ordinary taxable-goods movement "
            "with no exemption or special handling requirement?",
            95,
        ),
    ]:
        if plan.get(attribute) is None:
            questions.append(
                InformationGainQuestionRead(
                    question_id=f"q-{attribute}",
                    shipment_id=shipment["id"],
                    attribute_key=attribute,
                    question=question,
                    impact_score=score,
                    affects_rules=["IN-DOM-INVOICE-001"],
                    why_this_matters=(
                        "Determines whether the supported domestic rule set covers this movement."
                    ),
                    answer_options=["yes", "no"],
                )
            )
    for item in shipment.get("consignments", []):
        detail = item.get("domestic") or {}
        if (
            detail.get("destination", {}).get("state") == plan["origin"]["state"]
            and detail.get("eway_bill_required") is None
        ):
            attribute = f"eway_bill_required:{item['id']}"
            questions.append(
                InformationGainQuestionRead(
                    question_id=f"q-eway-{item['id']}",
                    shipment_id=shipment["id"],
                    consignment_id=item["id"],
                    attribute_key=attribute,
                    question=(
                        f"Does the applicable state notification require an e-way bill "
                        f"for {item['product_name']}?"
                    ),
                    impact_score=90,
                    affects_rules=["IN-DOM-EWAY-STATE-001"],
                    why_this_matters=(
                        "Intrastate applicability cannot be inferred "
                        "from the national threshold alone."
                    ),
                    answer_options=["yes", "no"],
                )
            )
    return questions


def domestic_routes(shipment, events, documents, rules, evaluate_compliance, answers=None):
    assessment = evaluate_compliance(shipment, events, documents, rules, answers=answers)
    legs = sorted(shipment.get("route_legs", []), key=lambda leg: leg["sequence_number"])
    locations = [shipment["domestic"]["origin"]] + [leg["domestic"]["destination"] for leg in legs]
    labels = [f"{place['city']}, {place['state']}" for place in locations]
    distance = sum(leg["domestic"]["distance_km"] for leg in legs)
    ready = assessment.status == ComplianceStatus.COMPLIANT
    paths = {}
    for item in shipment["consignments"]:
        stop = item["domestic"]["destination"]["pincode"]
        end = next(
            (i for i, place in enumerate(locations) if i > 0 and place["pincode"] == stop),
            len(labels) - 1,
        )
        paths[item["id"]] = labels[: end + 1]
    option = RouteOptionRead(
        route_id="domestic-planned",
        label="Planned domestic route",
        description=(
            "User-entered distance; estimated driving time assumes 40 km/h. "
            "Alternate routes need verified distances and all delivery stops."
        ),
        countries=labels,
        per_consignment_paths=paths,
        is_current_route=True,
        legal_status="VALID" if ready else "REVIEW_REQUIRED",
        compliance_status=assessment.status,
        score=round(distance / 40, 1),
        estimated_duty=0,
        fta_eligible=False,
        risk_score=0,
        estimated_delay_hours=round(distance / 40, 1),
        required_documents=sorted(
            {doc for rule in assessment.applicable_rules for doc in rule.required_documents}
        ),
        missing_documents=assessment.missing_documents,
        corrective_actions=[assessment.recommended_action],
        is_recommended=ready,
    )
    return RouteOptimizationRead(
        shipment_id=shipment["id"],
        generated_at=datetime.now(UTC),
        recommended_route_id=option.route_id if ready else None,
        options=[option],
    )
