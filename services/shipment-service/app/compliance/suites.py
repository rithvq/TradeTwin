"""Registered immutable publication tests. Clients cannot supply expected results."""

from copy import deepcopy
from datetime import datetime

from app.trades.terms import digest

from .expression import ENGINE_VERSION, evaluate

SUITE_ID = "PH4_REQUIRED_BOUNDARIES_V1"
FAMILY = "INDIA_ORDINARY_ROAD_V1"
CORE_CODES = {
    "MOVEMENT_INVOICE",
    "INVOICE_FORMALITIES",
    "HSN_DIGITS",
    "EINVOICE_REQUIRED",
    "EINVOICE_PROOF",
    "IRP_REPORTING_CONTROL",
    "EWB_REQUIRED",
    "EWB_IDENTITY",
    "EWB_VALIDITY",
    "EWB_ARRIVAL_WINDOW",
    "EWB_PORTAL_CONTROLS",
    "CARRIED_DOCUMENTS",
    "AUTHORITY_ASSURANCE",
    "TRANSPORT_ASSURANCE",
    "LOADING_MANIFEST",
    "SUPPORTED_SCOPE",
    "INVOICE_RESERVATION",
}
BOUNDARIES = [
    {
        "rule_code": "EWB_REQUIRED",
        "input": {"invoice": {"grand_total_minor": value}},
        "expected": expected,
    }
    for value, expected in [("4999999", False), ("5000000", False), ("5000001", True), (None, None)]
] + [
    {
        "rule_code": "EINVOICE_REQUIRED",
        "input": {"turnover": {"exceeds_five_crore": threshold, "exclusion_resolved": exclusion}},
        "expected": expected,
    }
    for threshold, exclusion, expected in [
        (False, True, False),
        (True, True, True),
        (None, True, None),
        (True, None, None),
    ]
]
SUITE_HASH = digest(
    {
        "id": SUITE_ID,
        "engine": ENGINE_VERSION,
        "core_codes": sorted(CORE_CODES),
        "boundaries": BOUNDARIES,
    }
)

PREDICATES = dict(
    zip(
        sorted(CORE_CODES),
        [
            "authority_assurance",
            "carried_documents",
            "einvoice_proof",
            "einvoice_present",
            "ewb_arrival_window",
            "ewb_identity",
            "ewb_portal_controls",
            "ewb_present",
            "ewb_validity",
            "hsn_digits",
            "invoice_formalities",
            "invoice_reservation",
            "irp_reporting_window",
            "loading_manifest",
            "movement_invoice",
            "scope_supported",
            "transport_assurance",
        ],
        strict=True,
    )
)
SCOPE_INPUT = {
    "inherited": {
        "scope": "DOMESTIC_INTERSTATE",
        "movement_purpose": "SALE",
        "currency": "INR",
        "transport_mode": "ROAD",
        "transaction_layout": "REGULAR",
        "seller_registration_position": "REGISTERED",
        "buyer_registration_position": "REGISTERED",
        "seller_tax_scheme": "REGULAR",
        "seller_establishment_kind": "NORMAL",
        "buyer_establishment_kind": "NORMAL",
        "hazardous_declared": False,
        "temperature_controlled": False,
        "origin_state_code": "29",
        "destination_state_code": "33",
        "seller_registration_state_code": "29",
        "buyer_registration_state_code": "33",
    },
    "facts": {
        "over_dimensional_cargo_declared": False,
        "supply_taxability": "TAXABLE",
        "special_valuation_profile": "NONE_DECLARED",
        "reverse_charge_position": "NO",
        "document_issue_scenario": "ONE_INVOICE_PER_CONSIGNMENT",
    },
}
UNSUPPORTED_SCOPE = {
    "inherited.scope": "INTERNATIONAL",
    "inherited.movement_purpose": "JOB_WORK",
    "inherited.transport_mode": "AIR",
    "inherited.currency": "USD",
    "inherited.transaction_layout": "BILL_TO_SHIP_TO",
    "inherited.seller_registration_position": "UNREGISTERED",
    "inherited.buyer_registration_position": "UNREGISTERED",
    "inherited.seller_tax_scheme": "COMPOSITION",
    "inherited.seller_establishment_kind": "SEZ_UNIT",
    "inherited.buyer_establishment_kind": "SEZ_DEVELOPER",
    "inherited.hazardous_declared": True,
    "inherited.temperature_controlled": True,
    "facts.over_dimensional_cargo_declared": True,
    "facts.supply_taxability": "EXEMPT",
    "facts.special_valuation_profile": "IDENTIFIED_SPECIAL_PROFILE",
    "facts.reverse_charge_position": "YES",
    "facts.document_issue_scenario": "ONE_INVOICE_MULTIPLE_DISPATCHES",
    "inherited.seller_registration_state_code": "27",
    "inherited.buyer_registration_state_code": "27",
}
SUITE_HASH = digest(
    {
        "suite": SUITE_HASH,
        "required_proof_dimensions": PREDICATES,
        "scope": SCOPE_INPUT,
        "scope_cases": UNSUPPORTED_SCOPE,
        "revision": 4,
    }
)


def run(pack):
    rules = {r["rule_code"]: r for r in pack["rules"]}
    results = []
    scope = pack["supported_scope_predicate"]
    results.append(
        {
            "code": "SUPPORTED_ORDINARY_SCOPE",
            "passed": evaluate(scope, SCOPE_INPUT) is True
            and evaluate(pack["excluded_scope_predicate"], SCOPE_INPUT) is False,
        }
    )
    for path, unsupported in UNSUPPORTED_SCOPE.items():
        section, field = path.split(".")
        for value, expected in [(unsupported, False), (None, None)]:
            inputs = deepcopy(SCOPE_INPUT)
            inputs[section][field] = value
            results.append(
                {"code": f"SCOPE_{path}_{value}", "passed": evaluate(scope, inputs) is expected}
            )
    for code in sorted(CORE_CODES):
        rule = rules.get(code)
        results.append(
            {
                "code": "MANDATORY_" + code,
                "passed": bool(rule and rule["mandatory"] and not rule["waivable_warning"]),
            }
        )
        if rule:
            baseline = {
                "invoice": {"grand_total_minor": "5000001"},
                "turnover": {
                    "exceeds_five_crore": True,
                    "exclusion_resolved": True,
                    "irp_ten_crore_or_more": True,
                },
                "proof": {v: True for v in PREDICATES.values()},
            }
            applied = evaluate(rule["applicability_expression"], baseline)
            results.append({"code": "APPLICABLE_" + code, "passed": applied is True})
            for observed in (True, False, None):
                values = deepcopy(baseline)
                values["proof"][PREDICATES[code]] = observed
                actual = evaluate(rule["satisfaction_expression"], values)
                results.append({"code": f"PROOF_{code}_{observed}", "passed": actual is observed})
            start = datetime.fromisoformat(rule["effective_from"])
            end = (
                datetime.fromisoformat(rule["effective_until"])
                if rule.get("effective_until")
                else None
            )
            pack_start = datetime.fromisoformat(pack["effective_from"])
            pack_end = (
                datetime.fromisoformat(pack["effective_until"])
                if pack.get("effective_until")
                else None
            )
            results.append(
                {
                    "code": "COVERAGE_WINDOW_" + code,
                    "passed": start <= pack_start
                    and (end is None or (pack_end is not None and pack_end <= end)),
                }
            )
    for index, case in enumerate(BOUNDARIES):
        rule = rules.get(case["rule_code"])
        actual = (
            evaluate(rule["applicability_expression"], case["input"]) if rule else "MISSING_RULE"
        )
        results.append(
            {
                "code": f"BOUNDARY_{index}",
                "passed": actual is case["expected"],
                "expected": case["expected"],
                "actual": actual,
            }
        )
    results.append(
        {
            "code": "INDEPENDENT_REVIEW_POLICY",
            "passed": all(
                pack["separation_of_duties_policy"].get(k) is True
                for k in (
                    "independent_facts_review",
                    "independent_release_review",
                    "independent_publication",
                )
            ),
        }
    )
    results.append(
        {
            "code": "MODE_PROOF_SEPARATION",
            "passed": pack["environment"] == "SIMULATION"
            or all(p["policy"] != "SIMULATED_ONLY" for p in pack["proof_policy"].values()),
        }
    )
    return {
        "suite_id": SUITE_ID,
        "suite_hash": SUITE_HASH,
        "results": results,
        "passed": all(r["passed"] for r in results),
    }
