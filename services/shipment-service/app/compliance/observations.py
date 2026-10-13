"""Bounded evidence normalization; no private PAN/history is emitted by this module."""

from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import select

from app.document_desk.models import (
    Connection,
    FactRevision,
    TrustedKey,
    VerificationCheck,
    VerificationResult,
)
from app.trades.access import aware

from .models import TransportEvidence, TransportReview


def timestamp(value):
    try:
        return aware(datetime.fromisoformat(value)) if value else None
    except (ValueError, TypeError):
        return None


def same(actual, expected):
    return None if actual is None or expected is None else actual == expected


def together(values):
    return False if False in values else None if None in values else True


def observation(db, binding, kind, expected, policy, at, mode):
    """Only selected, current-input, authorised observations can satisfy a policy."""
    candidates, deadlines, dimensions = [], [], []
    bound = [
        binding.binding_json["movement_document"],
        *binding.binding_json.get("supporting_documents", []),
    ]
    references = {r["document_version_id"]: r["reviewed_fact_revision_id"] for r in bound}
    selected_ids = set(binding.binding_json.get("verification_result_ids", []))
    all_ids = set(
        db.scalars(
            select(VerificationResult.id)
            .join(VerificationCheck)
            .where(
                VerificationCheck.document_version_id.in_(references),
                VerificationCheck.check_type == kind,
            )
        )
    )
    for ident in sorted(selected_ids | all_ids):
        row = db.get(VerificationResult, ident)
        check = db.get(VerificationCheck, row.verification_check_id)
        if check.check_type != kind or check.document_version_id not in references:
            continue
        if check.fact_revision_id != references[check.document_version_id]:
            continue
        data = row.result_json
        normal = data.get("normalised_result", {})
        from .expression import get

        bound_fact = db.get(FactRevision, check.fact_revision_id)
        target = (
            get(bound_fact.canonical_document_json, check.target_field_path)
            if check.target_field_path
            else check.request_configuration_json.get("target_identifier", normal.get("identifier"))
        )
        if target != expected.get("identifier"):
            continue
        observed = timestamp(data.get("provider_observed_at")) or timestamp(data.get("checked_at"))
        max_age = policy.get("maximum_age_seconds", 900)
        deadline = min(
            [
                d
                for d in [
                    timestamp(data.get("fresh_until")),
                    observed + timedelta(seconds=max_age) if observed else None,
                ]
                if d is not None
            ],
            default=at,
        )
        dimensions.append(
            {
                "verification_result_id": ident,
                "selected": ident in selected_ids,
                "check_type": kind,
                "method": data.get("method"),
                "environment": data.get("provider_environment"),
                "lookup_outcome": data.get("lookup_outcome"),
                "signature_integrity": data.get("signature_integrity"),
                "issuer_trust": data.get("issuer_trust"),
                "identifier_match": data.get("identifier_match"),
                "checked_at": data.get("checked_at"),
                "provider_observed_at": data.get("provider_observed_at"),
                "fresh_until": deadline.isoformat(),
            }
        )
        policy_mode = policy.get("policy", "AUTHORISED_LIVE_ONLY")
        allowed = (
            mode == "SIMULATION"
            and policy_mode == "SIMULATED_ONLY"
            and data.get("provider_environment") == "SIMULATION"
        ) or (
            policy_mode != "SIMULATED_ONLY"
            and data.get("provider_environment") == "LIVE"
            and data.get("method") == "AUTHORISED_LOOKUP"
        )
        if mode == "PRODUCTION":
            connection = db.get(Connection, check.connection_id) if check.connection_id else None
            allowed = allowed and bool(
                connection
                and connection.status == "CONFIGURED"
                and connection.provider_environment == "LIVE"
                and kind in connection.allowed_check_types_json
            )
        if not allowed or observed is None or observed > at or at >= deadline:
            continue
        if data.get("lookup_outcome") in {
            "UNAVAILABLE",
            "NOT_CONFIGURED",
            "NOT_AUTHORISED",
            "ERROR",
            "NOT_CHECKED",
        }:
            candidates.append(None)
            continue
        matches = [same(normal.get(k), v) for k, v in expected.items()]
        for field in policy.get("required_observed_fields", []):
            matches.append(True if normal.get(field) is not None else None)
        matches.append(
            normal.get("status") == "ACTIVE" if normal.get("status") is not None else None
        )
        outcome = together(matches)
        if ident in selected_ids or outcome is False:
            candidates.append(outcome)
            deadlines.append(deadline)
    # Contradictory observations are blockers, never newest-observation-wins.
    if mode == "PRODUCTION" and policy.get("policy") == "AUTHORISED_LIVE_OR_REVIEWED_MANUAL":
        from app.document_desk.models import ManualAttestation
        from app.operations.models import Attachment

        from .models import ManualEvidence, ManualReview

        for ident in binding.binding_json.get("manual_attestation_ids", []):
            reported = db.get(ManualAttestation, ident)
            if (
                reported.check_type != kind
                or references.get(reported.document_version_id) != reported.fact_revision_id
                or reported.target_identifier != expected.get("identifier")
            ):
                continue
            fields = db.scalar(select(ManualEvidence).where(ManualEvidence.attestation_id == ident))
            review = db.scalar(
                select(ManualReview)
                .where(ManualReview.attestation_id == ident)
                .order_by(ManualReview.created_at.desc(), ManualReview.id.desc())
            )
            deadline = aware(reported.observed_at) + timedelta(
                seconds=policy["maximum_age_seconds"]
            )
            if (
                not fields
                or not review
                or review.decision != "APPROVE_DECLARATION"
                or review.created_by_user_id == reported.actor_user_id
                or at < aware(reported.observed_at)
                or at >= deadline
            ):
                continue
            if policy.get("supporting_evidence_required") and (
                not fields.supporting_attachment_ids
                or any(
                    db.get(Attachment, i).security_state != "CLEAN"
                    for i in fields.supporting_attachment_ids
                )
            ):
                continue
            normal = fields.observed_fields_json
            candidates.append(
                together(
                    [
                        *[same(normal.get(k), v) for k, v in expected.items()],
                        *[
                            True if normal.get(k) is not None else None
                            for k in policy["required_observed_fields"]
                        ],
                        same(reported.observed_status, "ACTIVE"),
                        same(normal.get("status"), "ACTIVE"),
                    ]
                )
            )
            deadlines.append(deadline)
            dimensions.append(
                {
                    "attestation_id": ident,
                    "selected": True,
                    "method": "MANUAL_REPORTED",
                    "review_status": "INDEPENDENTLY_APPROVED",
                    "check_type": kind,
                    "provider_observed_at": aware(reported.observed_at).isoformat(),
                    "environment": "LIVE_REPORTED",
                    "fresh_until": deadline.isoformat(),
                    "limitation": "Reviewed portal observation, not a live API response.",
                }
            )
    passed = False if False in candidates else True if True in candidates else None
    return passed, min(deadlines) if deadlines else None, dimensions


def signature(db, binding, invoice, mode, at):
    required = {
        "header.irn",
        "header.document_number",
        "header.issue_date",
        "parties.supplier.gstin",
        "parties.recipient.gstin",
        "totals.grand_total_minor",
    }
    failures, verified = False, False
    ref = binding.binding_json["movement_document"]
    selected = set(binding.binding_json.get("verification_result_ids", []))
    relevant = set(
        db.scalars(
            select(VerificationResult.id)
            .join(VerificationCheck)
            .where(
                VerificationCheck.document_version_id == ref["document_version_id"],
                VerificationCheck.fact_revision_id == ref["reviewed_fact_revision_id"],
                VerificationCheck.check_type.in_(["IRP_QR_SIGNATURE", "IRP_JSON_SIGNATURE"]),
            )
        )
    )
    for ident in sorted(selected | relevant):
        result = db.get(VerificationResult, ident)
        check = db.get(VerificationCheck, result.verification_check_id)
        if check.check_type not in {"IRP_QR_SIGNATURE", "IRP_JSON_SIGNATURE"}:
            continue
        ref = binding.binding_json["movement_document"]
        if (
            check.document_version_id != ref["document_version_id"]
            or check.fact_revision_id != ref["reviewed_fact_revision_id"]
        ):
            continue
        data = result.result_json
        expected_environment = "SIMULATION" if mode == "SIMULATION" else "LIVE"
        if data.get("provider_environment") != expected_environment:
            continue
        if data.get("signature_integrity") == "INVALID":
            failures = True
            continue
        if ident not in selected:
            continue
        key = db.get(TrustedKey, data.get("trusted_key_id")) if data.get("trusted_key_id") else None
        expected_environment = "SIMULATION" if mode == "SIMULATION" else "LIVE"
        if (
            not key
            or key.status != "ACTIVE"
            or key.key_purpose != "IRP_SIGNATURE"
            or key.algorithm != "RS256"
            or sha256(key.public_key_reference.encode()).hexdigest() != key.key_fingerprint
            or key.provider_environment != expected_environment
            or data.get("provider_environment") != expected_environment
        ):
            continue
        if (
            data.get("signature_integrity") != "VALID"
            or data.get("issuer_trust") != "TRUSTED_FOR_THIS_CHECK"
            or not required <= set(data.get("covered_field_paths", []))
        ):
            continue
        signed = data.get("normalised_result", {}).get("signed_document", {})
        if (key.effective_from and at < aware(key.effective_from)) or (
            key.effective_until and at >= aware(key.effective_until)
        ):
            continue
        comparisons = [
            same(signed.get("header", {}).get(k), invoice.get("header", {}).get(k))
            for k in ("irn", "document_number", "issue_date")
        ]
        comparisons += [
            same(
                (signed.get("parties", {}).get(k) or {}).get("gstin"),
                (invoice.get("parties", {}).get(k) or {}).get("gstin"),
            )
            for k in ("supplier", "recipient")
        ]
        comparisons.append(
            same(
                signed.get("totals", {}).get("grand_total_minor"),
                invoice.get("totals", {}).get("grand_total_minor"),
            )
        )
        verified = verified or together(comparisons) is True
        failures = failures or False in comparisons
    return False if failures else True if verified else None


def transport(db, binding, assignment, corridor, at, arrival, insurance_required):
    required = [
        "VEHICLE_RC",
        "VEHICLE_INSURANCE",
        "FITNESS_CERTIFICATE",
        "PUC_CERTIFICATE",
        "GOODS_PERMIT",
        "PERMIT_AUTHORISATION",
        "DRIVER_LICENCE",
    ]
    if insurance_required:
        required.append("CARGO_INSURANCE")
    outcomes, deadlines, details = [], [], []
    selected = [
        db.get(TransportEvidence, i)
        for i in binding.binding_json.get("transport_evidence_revision_ids", [])
    ]
    vehicle_number = assignment.vehicle_snapshot.get("registration_number")
    for kind in required:
        entries = [
            e for e in selected if e.evidence_type == kind and e.assignment_id == assignment.id
        ]
        candidates = []
        for entry in entries:
            review = db.scalar(
                select(TransportReview)
                .where(TransportReview.evidence_revision_id == entry.id)
                .order_by(TransportReview.created_at.desc(), TransportReview.id.desc())
            )
            data = entry.evidence_json
            from app.document_desk.models import Asset, Document, Version
            from app.operations.models import Attachment

            source = (
                db.get(Version, entry.document_version_id) if entry.document_version_id else None
            )
            document = db.get(Document, source.document_id) if source else None
            if document and (
                document.current_version_id != entry.document_version_id
                or document.effective_fact_revision_id != entry.reviewed_fact_revision_id
                or document.lifecycle_status != "ACTIVE"
            ):
                candidates.append(False)
                continue
            if source and any(
                db.get(Attachment, a.attachment_id).security_state != "CLEAN"
                or db.get(Attachment, a.attachment_id).sha256 != a.asset_sha256
                for a in db.scalars(select(Asset).where(Asset.document_version_id == source.id))
            ):
                candidates.append(False)
                continue
            if (
                not review
                or review.decision != "APPROVE_DECLARATION"
                or data.get("source_mode") == "SELF_DECLARATION"
                or not entry.document_version_id
            ):
                continue
            start, end = timestamp(data.get("valid_from")), timestamp(data.get("valid_until"))
            tests = [
                True if data.get("document_number") else None,
                True if data.get("issuing_authority") else None,
                None if not start or not end else start <= at < end,
                None if not end or not arrival else arrival < end,
            ]
            if kind == "DRIVER_LICENCE":
                tests.append(same(data.get("covered_driver_reference"), assignment.driver_user_id))
                tests.append(
                    assignment.vehicle_snapshot.get("vehicle_type")
                    in data.get("covered_vehicle_classes", [])
                    if data.get("covered_vehicle_classes")
                    else None
                )
            elif kind != "CARGO_INSURANCE":
                tests.append(same(data.get("covered_vehicle_number"), vehicle_number))
            if kind in {"GOODS_PERMIT", "PERMIT_AUTHORISATION"}:
                tests.append(
                    True
                    if data.get("permit_basis")
                    in {"NATIONAL", "STATE_WITH_ENDORSEMENTS", "TEMPORARY"}
                    else None
                )
                tests.append(
                    set(corridor) <= set(data.get("covered_states", []))
                    if data.get("covered_states")
                    else None
                )
                if data.get("route_restriction_position") != "NONE_DECLARED" or data.get(
                    "route_restrictions"
                ):
                    tests.append(None)  # Free-text restrictions require a supported interpretation.
            if kind == "PERMIT_AUTHORISATION":
                tests.append(
                    entry.parent_permit_evidence_revision_id
                    in {e.id for e in selected if e.evidence_type == "GOODS_PERMIT"}
                )
            if data.get("source_mode") in {"ISSUER_DIGITAL_RECORD", "AUTHORISED_LOOKUP"}:
                observed = db.get(VerificationResult, entry.verification_result_id)
                value = observed.result_json if observed else {}
                deadline = timestamp(value.get("fresh_until"))
                tests.append(None if not deadline else at < deadline)
                tests.append(same(value.get("normalised_result", {}).get("status"), "ACTIVE"))
                if deadline:
                    deadlines.append(deadline)
            result = together(tests)
            candidates.append(result)
            if end:
                deadlines.append(end)
            details.append(
                {
                    "evidence_revision_id": entry.id,
                    "type": kind,
                    "outcome": result,
                    "valid_until": end.isoformat() if end else None,
                }
            )
        outcomes.append(False if False in candidates else True if True in candidates else None)
    return together(outcomes), min(deadlines) if deadlines else None, details


def invoice_formalities(invoice, inherited, at):
    header, totals = invoice.get("header", {}), invoice.get("totals", {})
    parties, lines = invoice.get("parties", {}), invoice.get("lines", [])
    required = [
        header.get("document_number"),
        header.get("issue_date"),
        header.get("place_of_supply_state_code"),
        header.get("reverse_charge_position"),
        totals.get("taxable_subtotal_minor"),
        totals.get("grand_total_minor"),
    ]
    for name in ("supplier", "recipient"):
        party = parties.get(name) or {}
        required += [
            party.get("legal_name"),
            party.get("gstin"),
            (party.get("address") or {}).get("address_line1"),
        ]
    required += [
        line.get(key)
        for line in lines
        for key in (
            "description",
            "quantity",
            "uqc",
            "taxable_value_minor",
            "hsn_code",
            "igst_amount_minor",
            "declared_igst_rate_percent",
        )
    ]
    presence = None if not lines or any(v is None or v == "" for v in required) else True
    issuance = header.get("issuance_form")
    issuance_ok = (
        True
        if issuance == "ELECTRONIC_IT_ACT_DECLARED"
        else same(header.get("signature_presence"), "OBSERVED")
        if issuance == "PAPER_WITH_SIGNATURE"
        else None
    )
    number = header.get("document_number")
    number_ok = (
        None
        if number is None
        else len(number) <= 16
        and all(c.isalnum() or c in "/-" for c in number)
        and number.isascii()
    )
    issue_date = header.get("issue_date")
    from zoneinfo import ZoneInfo

    local_date = at.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    return together(
        [
            presence,
            issuance_ok,
            number_ok,
            same(header.get("place_of_supply_state_code"), inherited["destination_state_code"]),
            same(header.get("reverse_charge_position"), "NO"),
            None if issue_date is None else issue_date <= local_date,
            same((parties.get("supplier") or {}).get("gstin"), inherited["seller_gstin"]),
            same((parties.get("recipient") or {}).get("gstin"), inherited["buyer_gstin"]),
        ]
    )
