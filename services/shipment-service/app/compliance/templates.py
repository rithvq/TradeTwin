"""Reviewable candidate rule data, not an automatically published legal policy."""

from .schemas_rules import PackInput
from .suites import FAMILY


def literal(value):
    return {"op": "literal", "value": value}


def field(path, kind="value"):
    return {"op": "field", "path": path, "type": kind}


def compare(op, path, value, kind="value"):
    return {"op": op, "args": [field(path, kind), literal(value)], "type": kind}


def candidate(source_ids, environment="SIMULATION", version="1"):
    einvoice = {
        "op": "and",
        "args": [
            field("turnover.exceeds_five_crore", "boolean"),
            field("turnover.exclusion_resolved", "boolean"),
        ],
    }
    ewb = compare("gt", "invoice.grand_total_minor", "5000000", "money")
    predicates = {
        "SUPPORTED_SCOPE": (
            "scope_supported",
            literal(True),
            "APPLICATION_POLICY",
            "Published ordinary-goods scope, commodity and complete declared corridor "
            "must be supported. Unsupported scenarios require a scope-extension request, "
            "not a waiver.",
        ),
        "MOVEMENT_INVOICE": (
            "movement_invoice",
            literal(True),
            "LEGAL_REQUIREMENT",
            "Issued tax invoice before removal; a purchase order is not a movement invoice.",
        ),
        "INVOICE_FORMALITIES": (
            "invoice_formalities",
            literal(True),
            "LEGAL_REQUIREMENT",
            "Reviewed Rule 46 particulars, identity, place of supply, reverse-charge position "
            "and supported issuance form.",
        ),
        "HSN_DIGITS": (
            "hsn_digits",
            literal(True),
            "LEGAL_REQUIREMENT",
            "HSN digits use immediately preceding financial-year turnover, "
            "not maximum historical PAN turnover.",
        ),
        "EINVOICE_REQUIRED": (
            "einvoice_present",
            einvoice,
            "LEGAL_REQUIREMENT",
            "Applicable PAN-level preceding financial-year threshold and resolved supplier "
            "exclusion require an e-invoice.",
        ),
        "EINVOICE_PROOF": (
            "einvoice_proof",
            einvoice,
            "APPLICATION_POLICY",
            "Printed IRN alone is insufficient: require covered-field signature integrity, "
            "trusted key and current policy-approved IRN status.",
        ),
        "IRP_REPORTING_CONTROL": (
            "irp_reporting_window",
            field("turnover.irp_ten_crore_or_more", "boolean"),
            "PORTAL_CONTROL",
            "Separate IRP reporting restriction: report within 30 calendar days including "
            "invoice date; not the statutory five-crore applicability threshold.",
        ),
        "EWB_REQUIRED": (
            "ewb_present",
            ewb,
            "LEGAL_REQUIREMENT",
            "Ordinary supported issued consignment value strictly exceeding 50,000 INR "
            "requires an e-way bill; quoted values are not used.",
        ),
        "EWB_IDENTITY": (
            "ewb_identity",
            ewb,
            "LEGAL_REQUIREMENT",
            "Completed Part B, exact issued invoice, parties, value, road mode and "
            "currently assigned vehicle must match.",
        ),
        "EWB_VALIDITY": (
            "ewb_validity",
            ewb,
            "LEGAL_REQUIREMENT",
            "Required e-way bill must be active and within the authority-returned "
            "validity interval at dispatch.",
        ),
        "EWB_ARRIVAL_WINDOW": (
            "ewb_arrival_window",
            ewb,
            "APPLICATION_POLICY",
            "Expected arrival must be before required evidence expiry; this is a planning "
            "blocker distinct from current legal validity.",
        ),
        "EWB_PORTAL_CONTROLS": (
            "ewb_portal_controls",
            ewb,
            "PORTAL_CONTROL",
            "Generation within 180 days of document date and extension no later than "
            "360 days from generation; held enhancements are not active controls.",
        ),
        "CARRIED_DOCUMENTS": (
            "carried_documents",
            literal(True),
            "LEGAL_REQUIREMENT",
            "Selected permitted invoice and applicable e-way bill representation must be "
            "carried and acknowledged by the assigned driver.",
        ),
        "AUTHORITY_ASSURANCE": (
            "authority_assurance",
            literal(True),
            "APPLICATION_POLICY",
            "Independent active supplier and recipient registration observations within "
            "published policy freshness windows.",
        ),
        "TRANSPORT_ASSURANCE": (
            "transport_assurance",
            literal(True),
            "APPLICATION_POLICY",
            "Reviewed current vehicle/driver records, independent permit and "
            "permit-authorisation validity, full declared corridor coverage, "
            "and agreed cargo insurance.",
        ),
        "LOADING_MANIFEST": (
            "loading_manifest",
            literal(True),
            "APPLICATION_POLICY",
            "Exact complete prepared quantity/UQC, weight and package manifest pins pickup.",
        ),
        "INVOICE_RESERVATION": (
            "invoice_reservation",
            literal(True),
            "APPLICATION_POLICY",
            "Exclusive business invoice identity reservation; "
            "movement never frees a consumed invoice.",
        ),
    }
    scope = {
        "inherited.scope": "DOMESTIC_INTERSTATE",
        "inherited.movement_purpose": "SALE",
        "inherited.currency": "INR",
        "inherited.transport_mode": "ROAD",
        "inherited.transaction_layout": "REGULAR",
        "inherited.seller_registration_position": "REGISTERED",
        "inherited.buyer_registration_position": "REGISTERED",
        "inherited.seller_tax_scheme": "REGULAR",
        "inherited.seller_establishment_kind": "NORMAL",
        "inherited.buyer_establishment_kind": "NORMAL",
        "inherited.hazardous_declared": False,
        "inherited.temperature_controlled": False,
        "facts.over_dimensional_cargo_declared": False,
        "facts.supply_taxability": "TAXABLE",
        "facts.special_valuation_profile": "NONE_DECLARED",
        "facts.reverse_charge_position": "NO",
        "facts.document_issue_scenario": "ONE_INVOICE_PER_CONSIGNMENT",
    }
    rules = [
        {
            "rule_code": code,
            "rule_version": version,
            "requirement_code": code,
            "class": kind,
            "date_basis": "INVOICE_DATE"
            if code
            in {"HSN_DIGITS", "EINVOICE_REQUIRED", "EINVOICE_PROOF", "IRP_REPORTING_CONTROL"}
            else "ACTION_TIME",
            "effective_from": (
                "2021-04-01T00:00:00+05:30"
                if code == "HSN_DIGITS"
                else "2023-08-01T00:00:00+05:30"
                if code in {"EINVOICE_REQUIRED", "EINVOICE_PROOF"}
                else "2025-01-01T00:00:00+05:30"
                if code == "EWB_PORTAL_CONTROLS"
                else "2025-04-01T00:00:00+05:30"
            ),
            "effective_until": None,
            "applicability_expression": applicability,
            "satisfaction_expression": field("proof." + predicate, "boolean"),
            "dependency_paths": ["proof." + predicate],
            "required_evidence_types": [code],
            "allowed_proof_methods": ["REVIEWED_SOURCE"],
            "mandatory": True,
            "severity": "BLOCKER",
            "waivable_warning": False,
            "source_ids": source_ids,
            "explanation_template": explanation,
            "remedy_codes": ["CORRECT_BOUND_EVIDENCE", "REEVALUATE"],
        }
        for code, (predicate, applicability, kind, explanation) in predicates.items()
    ]
    policy = "SIMULATED_ONLY" if environment == "SIMULATION" else "AUTHORISED_LIVE_ONLY"
    proofs = {
        key: {
            "policy": policy,
            "maximum_age_seconds": age,
            "required_target_identifiers": ["identifier"],
            "required_observed_fields": fields,
            "supporting_evidence_required": True,
            "manual_review_permission": "document.manual_observation.review",
            "limitations": ["Explicit simulation proof; never production evidence."]
            if environment == "SIMULATION"
            else ["Authorised provider required; outage remains unavailable."],
        }
        for key, age, fields in [
            ("GSTIN", 86400, ["identifier", "status"]),
            ("IRN", 900, ["identifier", "status"]),
            (
                "EWB",
                900,
                [
                    "identifier",
                    "status",
                    "supplier_gstin",
                    "recipient_gstin",
                    "document_number",
                    "document_date",
                    "invoice_value_minor",
                    "vehicle_registration_number",
                    "transport_mode",
                    "part_information",
                    "valid_until",
                ],
            ),
        ]
    }
    return PackInput.model_validate(
        {
            "family_code": FAMILY,
            "version": version,
            "environment": environment,
            "title": "India ordinary interstate road sale - reviewable candidate",
            "input_schema_version": "COMPLIANCE_FACTS_V1",
            "rule_schema_version": "PH4_TYPED_RULES_V1",
            "supported_scope_predicate": {
                "op": "and",
                "args": [compare("eq", k, v) for k, v in scope.items()]
                + [
                    {
                        "op": "eq",
                        "args": [
                            field("inherited.seller_registration_state_code"),
                            field("inherited.origin_state_code"),
                        ],
                    },
                    {
                        "op": "eq",
                        "args": [
                            field("inherited.buyer_registration_state_code"),
                            field("inherited.destination_state_code"),
                        ],
                    },
                    {
                        "op": "ne",
                        "args": [
                            field("inherited.origin_state_code"),
                            field("inherited.destination_state_code"),
                        ],
                    },
                ],
            },
            "excluded_scope_predicate": literal(False),
            "coverage_dimensions": {
                "GST_MOVEMENT_DOCUMENTS": "COVERED",
                "DOCUMENT_CONSISTENCY": "COVERED",
                "AUTHORITY_OBSERVATION_ASSURANCE": "COVERED",
                "ROAD_TRANSPORT_ASSURANCE": "COVERED",
                "COMMODITY_RESTRICTIONS": "NOT_ASSESSED",
                "CONTRACTUAL_CARGO_INSURANCE": "COVERED",
                "TAX_RATE_DETERMINATION": "NOT_ASSESSED",
                "ROUTE_OPTIMIZATION": "NOT_ASSESSED",
            },
            "effective_from": "2025-04-01T00:00:00+05:30",
            "source_ids": source_ids,
            "limitations": [
                "Narrow ordinary domestic interstate sale only. "
                "No customs clearance or government issuance.",
                "No hazardous goods, cold chain, job work, special valuation, split invoices "
                "or complex establishment layouts.",
            ],
            "proof_policy": proofs,
            "separation_of_duties_policy": {
                "independent_facts_review": True,
                "independent_release_review": True,
                "independent_publication": True,
            },
            "supported_scope_codes": ["ORDINARY_TAXABLE_INTERSTATE_ROAD_SALE"],
            "supported_commodity_codes": ["ORDINARY_COTTON_SHIRTS"],
            "supported_corridors": [["29", "33"]],
            "rules": rules,
        }
    )
