"""Versioned data comparisons, not statutory applicability or dispatch decisions."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.operations.models import (
    Payment,
)
from app.trades.access import aware
from app.trades.models import Item, Revision, Snapshot, Trade, now, uid
from app.trades.terms import digest

from . import access
from .context import CHECK_PACK, freshness
from .ledger import record, result
from .models import (
    Assessment,
    Asset,
    Document,
    FactRevision,
    Finding,
    FindingAnnotation,
    LineMapping,
    SubjectLink,
    VerificationCheck,
    VerificationResult,
)

CODES = (
    "DOCUMENT_IDENTITY_COMPLETE",
    "IDENTIFIER_FORMAT",
    "PARTY_GSTIN_MATCH",
    "PARTY_NAME_DIFFERENCE",
    "BILL_FROM_ADDRESS_MATCH",
    "BILL_TO_ADDRESS_MATCH",
    "DISPATCH_ADDRESS_MATCH",
    "SHIP_TO_ADDRESS_MATCH",
    "PO_REFERENCE_MATCH",
    "DOCUMENT_REFERENCE_MATCH",
    "LINE_MAPPING_QUANTITY_CAP",
    "CONSIGNMENT_MAPPING_QUANTITY_CAP",
    "UQC_MATCH",
    "HSN_DECLARATION_DIFFERENCE",
    "DECLARED_LINE_ARITHMETIC",
    "DECLARED_TOTAL_ARITHMETIC",
    "PRICE_BASIS_COMPARABLE",
    "DECLARED_PRICE_DIFFERENCE",
    "VEHICLE_REFERENCE_MATCH",
    "CARRIER_REFERENCE_MATCH",
    "PACKING_WEIGHT_DIFFERENCE",
    "PACKING_PACKAGE_DIFFERENCE",
    "EWB_PRINTED_TIME_WINDOW",
    "SIGNED_PAYLOAD_PRINTED_FIELD_MATCH",
    "DUPLICATE_PRESENTATION_CANDIDATE",
    "PAYMENT_EVIDENCE_REFERENCE_MATCH",
    "PAYMENT_EVIDENCE_AMOUNT_MATCH",
    "POD_RECEIPT_REFERENCE_MATCH",
)


def duplicate_candidates(db, ctx, doc):
    fact = (
        db.get(FactRevision, doc.effective_fact_revision_id)
        if doc.effective_fact_revision_id
        else None
    )
    own_hashes = set(
        db.scalars(
            select(Asset.asset_sha256).where(
                Asset.document_version_id == doc.current_version_id, Asset.role == "PRIMARY"
            )
        )
    )
    canonical = fact.canonical_document_json if fact else {}
    supplier = (canonical.get("parties") or {}).get("supplier") or {}
    issuer = supplier.get("gstin") or supplier.get("legal_name")
    number = (canonical.get("header") or {}).get("document_number")
    date = (canonical.get("header") or {}).get("issue_date")
    candidates = []
    for other in db.scalars(
        select(Document).where(Document.trade_id == doc.trade_id, Document.id != doc.id)
    ):
        if not access.can_read(db, ctx, other) or other.canonical_document_id:
            continue
        hashes = set(
            db.scalars(
                select(Asset.asset_sha256).where(
                    Asset.document_version_id == other.current_version_id,
                    Asset.role == "PRIMARY",
                )
            )
        )
        duplicate_hash = bool(own_hashes & hashes)
        other_fact = (
            db.get(FactRevision, other.effective_fact_revision_id)
            if other.effective_fact_revision_id
            else None
        )
        values = other_fact.canonical_document_json if other_fact else {}
        other_supplier = (values.get("parties") or {}).get("supplier") or {}
        other_issuer = other_supplier.get("gstin") or other_supplier.get("legal_name")
        other_header = values.get("header") or {}
        identity_match = (
            issuer
            and other_issuer
            and issuer.casefold() == other_issuer.casefold()
            and number
            and number == other_header.get("document_number")
        )
        period_match = (
            date and other_header.get("issue_date") and date[:4] == other_header["issue_date"][:4]
        )
        if duplicate_hash or (
            identity_match
            and period_match
            and (
                other.document_type == doc.document_type
                or {other.document_type, doc.document_type} <= access.INVOICE_PRESENTATIONS
            )
        ):
            candidates.append(
                {
                    "document_id": other.id,
                    "version_id": other.current_version_id,
                    "fact_revision_id": other.effective_fact_revision_id,
                    "basis": "FILE_HASH" if duplicate_hash else "REVIEWED_DECLARED_IDENTITY",
                    "requires_human_canonical_selection": True,
                }
            )
    return sorted(candidates, key=lambda c: (c["document_id"], c["version_id"]))


def compare(db, ctx, doc, version, fact, mapping, context):
    tolerance = Decimal(str(context.get("arithmetic_tolerance_minor", "1")))
    canonical = fact.canonical_document_json
    trade = db.get(Trade, doc.trade_id)
    accepted = (
        db.get(Revision, context["accepted_revision_id"])
        if context["accepted_revision_id"]
        else None
    )
    facts = accepted.facts_json if accepted else {}
    row = Assessment(
        id=uid(),
        job_attempt_id=ctx.attempt_id,
        document_version_id=version.id,
        fact_revision_id=fact.id,
        mapping_revision_id=mapping.id if mapping else None,
        accepted_trade_revision_id=accepted.id if accepted else None,
        assessment_stage="REVIEWED_DATA_CHECK"
        if doc.effective_fact_revision_id == fact.id
        else "PROVISIONAL",
        check_pack_version=CHECK_PACK,
        input_fingerprint=digest(context),
        source_context_json=context,
        status="SUCCEEDED",
    )
    db.add(row)
    pending = []

    def emit(
        code,
        expected,
        observed,
        path,
        source=None,
        outcome=None,
        message=None,
        limits=None,
        severity="WARNING",
        dimension="CONSISTENCY",
    ):
        equal = expected == observed
        signed_numeric = code == "SIGNED_PAYLOAD_PRINTED_FIELD_MATCH" and (
            path.endswith("quantity") or path.endswith("_minor")
        )
        if (
            (
                signed_numeric
                or code
                in {
                    "PACKING_WEIGHT_DIFFERENCE",
                    "PACKING_PACKAGE_DIFFERENCE",
                    "PAYMENT_EVIDENCE_AMOUNT_MATCH",
                    "DECLARED_PRICE_DIFFERENCE",
                }
            )
            and expected is not None
            and observed is not None
        ):
            equal = Decimal(str(expected)) == Decimal(str(observed))
        resolved = outcome or (
            "UNKNOWN" if expected is None or observed is None else "PASS" if equal else "FAIL"
        )
        finding = Finding(
            id=uid(),
            assessment_run_id=row.id,
            check_code=code,
            check_version=CHECK_PACK,
            dimension=dimension,
            outcome=resolved,
            severity="INFO" if resolved in {"PASS", "NOT_EVALUATED"} else severity,
            expected_source_json=source
            or {
                "type": "ACCEPTED_TRADE_REVISION",
                "id": accepted.id if accepted else None,
                "trade_id": trade.id,
                "revision": accepted.revision_number if accepted else None,
                "field": path,
            },
            observed_source_json={
                "type": "DOCUMENT_FACT_REVISION",
                "document_id": doc.id,
                "document_version_id": version.id,
                "fact_revision_id": fact.id,
                "source_manifest_hash": version.source_manifest_hash,
                "field": path,
            },
            expected_value_json=expected,
            observed_value_json=observed,
            message=message
            or (
                "Executed comparison found equal values."
                if resolved == "PASS"
                else "Captured and expected values differ; review the two sources."
                if resolved == "FAIL"
                else "Expected or captured comparison data is missing."
            ),
            limitations_json=limits
            or [
                "Application data comparison only; not authenticity, legal applicability, "
                "or dispatch approval."
            ],
        )
        pending.append(finding)

    header, totals, parties = canonical["header"], canonical["totals"], canonical["parties"]
    emit(
        "DOCUMENT_IDENTITY_COMPLETE",
        True,
        bool(header.get("document_number") and header.get("issue_date")),
        "header",
        outcome="PASS" if header.get("document_number") and header.get("issue_date") else "UNKNOWN",
        dimension="COMPLETENESS",
    )
    import re

    for role in ("supplier", "recipient"):
        observed = (parties.get(role) or {}).get("gstin")
        emit(
            "IDENTIFIER_FORMAT",
            "GSTIN structure",
            observed,
            f"parties.{role}.gstin",
            outcome="UNKNOWN"
            if observed is None
            else "PASS"
            if re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", observed)
            else "FAIL",
            limits=["Structure is not checksum verification or active GST registration."],
        )
        business_role = "bill_from" if role == "supplier" else "bill_to"
        party_fact = facts.get(business_role) or {}
        snapshot = (
            db.get(
                Snapshot,
                accepted.seller_snapshot_id if role == "supplier" else accepted.buyer_snapshot_id,
            )
            if accepted
            else None
        )
        profile = (
            (snapshot.snapshot_json.get("profile") or snapshot.snapshot_json) if snapshot else {}
        )
        expected_name = profile.get("legal_name")
        # Organisation profiles may have changed; accepted party snapshots remain authoritative.
        emit(
            "PARTY_NAME_DIFFERENCE",
            expected_name.casefold() if expected_name else None,
            ((parties.get(role) or {}).get("legal_name") or "").casefold() or None,
            f"parties.{role}.legal_name",
        )
        expected_gstin = party_fact.get("gstin")
        emit("PARTY_GSTIN_MATCH", expected_gstin, observed, f"parties.{role}.gstin")
    for role, code in {
        "bill_from": "BILL_FROM_ADDRESS_MATCH",
        "bill_to": "BILL_TO_ADDRESS_MATCH",
        "dispatch_from": "DISPATCH_ADDRESS_MATCH",
        "ship_to": "SHIP_TO_ADDRESS_MATCH",
    }.items():
        expected = (
            (facts.get(role) or {}).get("billing_address")
            if role.startswith("bill_")
            else facts.get(role)
        )
        observed = (parties.get(role) or {}).get("address")
        if expected is None or observed is None:
            emit(code, expected, observed, f"parties.{role}.address")
        else:
            present = {k: v for k, v in observed.items() if v is not None}
            observed = {k: v for k, v in present.items() if k in expected}
            expected = {k: expected.get(k) for k in observed}
            emit(
                code,
                expected or None,
                observed or None,
                f"parties.{role}.address",
                limits=[
                    "Only captured address components are compared; "
                    "missing components remain unknown."
                ],
            )
    emit(
        "PO_REFERENCE_MATCH",
        facts.get("purchase_order_reference"),
        header.get("purchase_order_reference"),
        "header.purchase_order_reference",
    )
    related_sources = []
    for basis in context.get("related_documents", []):
        related_fact = (
            db.get(FactRevision, basis["fact_revision_id"]) if basis["fact_revision_id"] else None
        )
        if related_fact:
            related_sources.append((related_fact, related_fact.canonical_document_json))
    if related_sources:
        for related_fact, values in related_sources:
            emit(
                "DOCUMENT_REFERENCE_MATCH",
                values["header"].get("document_number"),
                canonical["eway_bill"].get("referenced_document_number"),
                "eway_bill.referenced_document_number",
                source={
                    "type": "RELATED_DOCUMENT_FACT_REVISION",
                    "id": related_fact.id,
                    "version_id": related_fact.document_version_id,
                    "field": "header.document_number",
                },
            )
            for role in ("supplier", "recipient"):
                emit(
                    "PARTY_GSTIN_MATCH",
                    (values["parties"].get(role) or {}).get("gstin"),
                    (parties.get(role) or {}).get("gstin"),
                    f"parties.{role}.gstin",
                    source={
                        "type": "RELATED_DOCUMENT_FACT_REVISION",
                        "id": related_fact.id,
                        "version_id": related_fact.document_version_id,
                        "field": f"parties.{role}.gstin",
                    },
                )
    mapped = (
        list(db.scalars(select(LineMapping).where(LineMapping.mapping_revision_id == mapping.id)))
        if mapping
        else []
    )
    sums, targets = defaultdict(Decimal), defaultdict(Decimal)
    items = (
        {
            i.line_ref: i
            for i in db.scalars(select(Item).where(Item.trade_revision_id == accepted.id))
        }
        if accepted
        else {}
    )
    for m in mapped:
        sums[m.document_line_ref] += m.mapped_quantity
        if m.consignment_item_id:
            targets[m.consignment_item_id] += m.mapped_quantity
        item = items.get(m.trade_line_ref)
        line = next(
            (
                line
                for line in canonical["lines"]
                if line["document_line_ref"] == m.document_line_ref
            ),
            None,
        )
        emit(
            "UQC_MATCH",
            item.uqc if item else None,
            line.get("uqc") if line else None,
            f"lines.{m.document_line_ref}.uqc",
        )
        emit(
            "HSN_DECLARATION_DIFFERENCE",
            item.hsn_code if item else None,
            line.get("hsn_code") if line else None,
            f"lines.{m.document_line_ref}.hsn_code",
        )
    for line in canonical["lines"]:
        path = f"lines.{line['document_line_ref']}"
        quantity = line.get("quantity")
        emit(
            "LINE_MAPPING_QUANTITY_CAP",
            quantity,
            str(sums[line["document_line_ref"]]),
            path + ".quantity",
            outcome="UNKNOWN"
            if quantity is None or not mapping
            else "PASS"
            if sums[line["document_line_ref"]] <= Decimal(quantity)
            else "FAIL",
        )
        if header.get("document_profile") != "SIMPLE_DECLARED_TOTALS":
            emit(
                "DECLARED_LINE_ARITHMETIC",
                None,
                None,
                path,
                outcome="NOT_EVALUATED",
                dimension="ARITHMETIC",
                limits=[
                    "Printed calculation profile is unresolved or unsupported; "
                    "no universal GST formula is assumed."
                ],
            )
        else:
            ready = all(
                line.get(k) is not None
                for k in (
                    "quantity",
                    "unit_price_minor",
                    "line_discount_minor",
                    "taxable_value_minor",
                )
            )
            expected = (
                Decimal(line["quantity"]) * Decimal(line["unit_price_minor"])
                - Decimal(line["line_discount_minor"])
                if ready
                else None
            )
            observed = (
                Decimal(line["taxable_value_minor"])
                if line.get("taxable_value_minor") is not None
                else None
            )
            emit(
                "DECLARED_LINE_ARITHMETIC",
                str(expected) if expected is not None else None,
                str(observed) if observed is not None else None,
                path,
                outcome="UNKNOWN"
                if expected is None or observed is None
                else "PASS"
                if abs(expected - observed) <= tolerance
                else "FAIL",
                dimension="ARITHMETIC",
                limits=["1-paise tolerance; validates declared arithmetic, not tax rates."],
            )
    target_snapshots = {
        i["id"]: i for c in context["consignments"] for i in c.get("items_snapshot", [])
    }
    for ident, total in targets.items():
        item = target_snapshots.get(ident)
        if not item:
            continue
        emit(
            "CONSIGNMENT_MAPPING_QUANTITY_CAP",
            item["allocated_quantity"],
            str(total),
            "mapped_quantity",
            source={"type": "CONSIGNMENT_ITEM", "id": ident, "field": "allocated_quantity"},
            outcome="PASS" if total <= Decimal(item["allocated_quantity"]) else "FAIL",
        )
    required_totals = (
        "taxable_subtotal_minor",
        "cgst_total_minor",
        "sgst_total_minor",
        "igst_total_minor",
        "cess_total_minor",
        "state_cess_total_minor",
        "other_charges_minor",
        "round_off_minor",
        "grand_total_minor",
    )
    if (
        header.get("document_profile") != "SIMPLE_DECLARED_TOTALS"
        or totals.get("discount_treatment") == "UNRESOLVED"
    ):
        emit(
            "DECLARED_TOTAL_ARITHMETIC",
            None,
            totals.get("grand_total_minor"),
            "totals",
            outcome="NOT_EVALUATED",
            dimension="ARITHMETIC",
        )
    else:
        ready = (
            all(totals.get(k) is not None for k in required_totals)
            and totals.get("discount_treatment") is not None
        )
        expected = sum(int(totals[k]) for k in required_totals[:-1]) if ready else None
        if ready and totals["discount_treatment"] == "SUBTRACT_AFTER_SUBTOTAL":
            expected = (
                expected - int(totals["discount_total_minor"])
                if totals.get("discount_total_minor") is not None
                else None
            )
        emit(
            "DECLARED_TOTAL_ARITHMETIC",
            str(expected) if expected is not None else None,
            totals.get("grand_total_minor"),
            "totals",
            outcome="UNKNOWN"
            if expected is None or totals.get("grand_total_minor") is None
            else "PASS"
            if abs(expected - int(totals["grand_total_minor"])) <= tolerance
            else "FAIL",
            dimension="ARITHMETIC",
            limits=[
                "Supported declared totals profile only; 1-paise tolerance, not tax-law approval."
            ],
        )
    basis = facts.get("pricing_basis")
    comparable = basis in {"NET_TAX_EXTRA", "TAX_INCLUSIVE", "TAX_INCLUDED"}
    emit(
        "PRICE_BASIS_COMPARABLE",
        basis,
        basis if comparable else None,
        "pricing_basis",
        outcome="PASS" if comparable else "UNKNOWN",
    )
    expected_price = (
        accepted.pricing_summary_json.get("quoted_goods_total_minor") if accepted else None
    )
    ordered_portions = defaultdict(Decimal)
    for portion in mapped:
        ordered_portions[portion.trade_line_ref] += portion.mapped_quantity
    complete_document = (
        bool(mapping)
        and bool(canonical["lines"])
        and all(
            line.get("quantity") is not None
            and sums[line["document_line_ref"]] == Decimal(line["quantity"])
            for line in canonical["lines"]
        )
    )
    full_order = complete_document and all(
        ordered_portions[item.line_ref] == item.quantity for item in items.values()
    )
    if not full_order:
        expected_price = None
        if (
            complete_document
            and basis == "NET_TAX_EXTRA"
            and all(
                items[ref].unit_price_minor is not None and not items[ref].discount_minor
                for ref in ordered_portions
            )
        ):
            partial = sum(
                (
                    quantity * items[ref].unit_price_minor
                    for ref, quantity in ordered_portions.items()
                ),
                Decimal(0),
            )
            if partial == partial.to_integral_value():
                expected_price = str(int(partial))
    observed_price = (
        totals.get("taxable_subtotal_minor")
        if basis == "NET_TAX_EXTRA"
        else totals.get("grand_total_minor")
        if comparable
        else None
    )
    if doc.document_type in access.FINANCIAL:
        emit(
            "DECLARED_PRICE_DIFFERENCE",
            str(expected_price) if expected_price is not None else None,
            observed_price,
            "totals",
            limits=[
                "NET_TAX_EXTRA compares taxable goods, not gross invoice total; "
                "final invoice settlement remains separate."
                " Partial invoices require complete mappings and an unambiguous discount basis."
            ],
        )
    consignments = context["consignments"]
    assigned = {c["assignment_id"] for c in consignments if c["assignment_id"]}
    assignments = [a for a in context["assignments"] if a["id"] in assigned]
    vehicles = {(a["vehicle_snapshot"] or {}).get("registration_number") for a in assignments}
    carrier_names = {a["carrier_legal_name"] for a in assignments}
    vehicle = next(iter(vehicles)) if len(vehicles) == 1 else None
    carrier = next(iter(carrier_names)) if len(carrier_names) == 1 else None
    emit(
        "VEHICLE_REFERENCE_MATCH",
        vehicle,
        canonical["packing_transport"].get("vehicle_registration_number")
        or canonical["eway_bill"].get("vehicle_registration_number"),
        "vehicle_registration_number",
        source={
            "type": "ASSIGNMENT_SNAPSHOT",
            "ids": [a["id"] for a in assignments],
            "field": "vehicle_snapshot.registration_number",
        },
    )
    emit(
        "CARRIER_REFERENCE_MATCH",
        carrier,
        canonical["packing_transport"].get("carrier_name"),
        "packing_transport.carrier_name",
        source={
            "type": "ASSIGNMENT_SNAPSHOT",
            "ids": [a["id"] for a in assignments],
            "field": "carrier_organization_id",
        },
    )
    for code, key in (
        ("PACKING_WEIGHT_DIFFERENCE", "declared_gross_weight_kg"),
        ("PACKING_PACKAGE_DIFFERENCE", "package_count"),
    ):
        values = [cn["plan_snapshot"].get(key) for cn in consignments]
        expected = (
            sum(Decimal(str(v)) for v in values)
            if values and all(v is not None for v in values)
            else None
        )
        name = "gross_weight_kg" if code == "PACKING_WEIGHT_DIFFERENCE" else "package_count"
        observed = canonical["packing_transport"].get(name)
        emit(
            code,
            str(expected) if expected is not None else None,
            str(Decimal(str(observed))) if observed is not None else None,
            f"packing_transport.{name}",
            source={
                "type": "CONSIGNMENT_PLAN",
                "ids": [c["id"] for c in consignments],
                "field": key,
            },
        )
    until = canonical["eway_bill"].get("valid_until_at")
    begins = canonical["eway_bill"].get("valid_from_at")
    clock = (
        aware(datetime.fromisoformat(context["assessment_observation"]["checked_at"]))
        if context.get("assessment_observation")
        else now()
    )
    emit(
        "EWB_PRINTED_TIME_WINDOW",
        clock.isoformat(),
        {"from": begins, "until": until},
        "eway_bill.valid_until_at",
        outcome="UNKNOWN"
        if until is None or begins is None
        else "PASS"
        if aware(datetime.fromisoformat(begins)) <= clock < aware(datetime.fromisoformat(until))
        else "FAIL",
        source={"type": "ASSESSMENT_CLOCK", "checked_at": clock.isoformat()},
        limits=["Printed time-window observation only; not current authoritative validity."],
    )
    candidates = context.get("assessment_observation", {}).get("duplicate_candidates")
    if candidates is None:
        candidates = duplicate_candidates(db, ctx, doc)
    emit(
        "DUPLICATE_PRESENTATION_CANDIDATE",
        [],
        candidates,
        "document_identity",
        outcome="FAIL" if candidates else "PASS",
        dimension="DUPLICATE",
        message="Duplicate candidate requires human canonical selection."
        if candidates
        else "No accessible duplicate candidate found.",
    )
    payment_links = (
        db.scalars(
            select(SubjectLink).where(
                SubjectLink.document_version_id == version.id,
                SubjectLink.subject_type == "PAYMENT",
                SubjectLink.revoked_at.is_(None),
            )
        )
        if doc.document_type == "PAYMENT_EVIDENCE"
        else []
    )
    for link in payment_links:
        payment = db.get(Payment, link.subject_id)
        for code, key, expected in (
            (
                "PAYMENT_EVIDENCE_REFERENCE_MATCH",
                "transaction_reference",
                payment.declared_reference,
            ),
            ("PAYMENT_EVIDENCE_AMOUNT_MATCH", "amount_minor", str(payment.amount_minor)),
        ):
            emit(
                code,
                expected,
                canonical["payment_evidence"].get(key),
                f"payment_evidence.{key}",
                source={"type": "REPORTED_PAYMENT", "id": payment.id, "field": key},
                limits=["Matching evidence does not acknowledge or bank-verify funds."],
            )
    for check in db.scalars(
        select(VerificationCheck).where(VerificationCheck.document_version_id == version.id)
    ):
        for verification in db.scalars(
            select(VerificationResult).where(VerificationResult.verification_check_id == check.id)
        ):
            value = verification.result_json
            if value["signature_integrity"] == "VALID":
                signed = value["normalised_result"].get("signed_document") or {}
                from .ledger import flatten

                observed_fields, signed_fields = flatten(canonical), flatten(signed)
                for path in value["covered_field_paths"]:
                    if "*" in path:
                        field = path.rsplit(".", 1)[-1]
                        signed_lines, printed_lines = signed.get("lines", []), canonical["lines"]
                        if len(signed_lines) == len(printed_lines) == 1:
                            emit(
                                "SIGNED_PAYLOAD_PRINTED_FIELD_MATCH",
                                signed_lines[0].get(field),
                                printed_lines[0].get(field),
                                f"lines.{printed_lines[0]['document_line_ref']}.{field}",
                                source={
                                    "type": "VERIFIED_SIGNED_PAYLOAD",
                                    "verification_result_id": verification.id,
                                    "field": path,
                                },
                                limits=[
                                    "Unambiguous single-line profile only; "
                                    "no live IRN status was checked."
                                ],
                            )
                        else:
                            emit(
                                "SIGNED_PAYLOAD_PRINTED_FIELD_MATCH",
                                None,
                                None,
                                path,
                                outcome="NOT_EVALUATED",
                                limits=[
                                    "Multiple rows require supported explicit correspondence; "
                                    "row order is not guessed."
                                ],
                            )
                    else:
                        emit(
                            "SIGNED_PAYLOAD_PRINTED_FIELD_MATCH",
                            signed_fields.get(path),
                            observed_fields.get(path),
                            path,
                            source={
                                "type": "VERIFIED_SIGNED_PAYLOAD",
                                "verification_result_id": verification.id,
                                "input_hash": value["input_hash"],
                                "field": path,
                            },
                            limits=[
                                "Only this signed payload's covered fields are compared; "
                                "no live IRN status was checked."
                            ],
                        )
    executed = {f.check_code for f in pending}
    for code in CODES:
        if code not in executed:
            emit(
                code,
                None,
                None,
                "",
                outcome="NOT_EVALUATED",
                limits=[
                    "This check has no supported linked input in the current document context."
                ],
            )
    db.add_all(pending)
    record(
        db,
        ctx,
        "DOCUMENT_ASSESSMENT_RECORDED",
        doc,
        version,
        {
            "assessment_id": row.id,
            "check_pack_version": CHECK_PACK,
            "input_fingerprint": row.input_fingerprint,
        },
    )
    return row


def assessment_view(db, ctx, row):
    _, doc, _ = access.version(db, ctx, row.document_version_id)
    if (
        not access.full_capture(db, ctx, doc)
        and row.fact_revision_id != doc.effective_fact_revision_id
    ):
        access.fail("NOT_FOUND", "Reviewed assessment not found.", status=404)
    # All related inputs must remain readable, even after a sharing revocation.
    for related in row.source_context_json.get("related_documents", []):
        _, other, _ = access.version(db, ctx, related["version_id"])
        if (
            not access.full_capture(db, ctx, other)
            and related["fact_revision_id"] != other.effective_fact_revision_id
        ):
            access.fail("NOT_FOUND", "Related reviewed evidence is not accessible.", status=404)
    for candidate in row.source_context_json.get("assessment_observation", {}).get(
        "duplicate_candidates", []
    ):
        access.version(db, ctx, candidate["version_id"])
    findings = [
        result(f, doc)
        for f in db.scalars(select(Finding).where(Finding.assessment_run_id == row.id))
    ]
    if not access.full_capture(db, ctx, doc):
        findings = [
            f
            for f in findings
            if f["expected_source_json"].get("type") != "VERIFIED_SIGNED_PAYLOAD"
        ]
    return {
        **result(row, doc),
        "freshness": freshness(db, doc, row.source_context_json, ctx),
        "findings": findings,
        "consistency": "DISCREPANCIES_FOUND"
        if any(f["outcome"] == "FAIL" for f in findings)
        else "INSUFFICIENT_DATA"
        if any(f["outcome"] == "UNKNOWN" for f in findings)
        else "NO_DISCREPANCIES_FOUND",
        "dispatch_readiness": "NOT_ASSESSED",
    }


def annotate(db, ctx, ident, payload):
    from app.operations.access import exists

    finding = exists(db, Finding, ident)
    assessment = exists(db, Assessment, finding.assessment_run_id)
    version, doc, _ = access.version(
        db, ctx, assessment.document_version_id, "document.check", True
    )
    if payload.related_new_assessment_id:
        other = exists(db, Assessment, payload.related_new_assessment_id)
        _, other_doc, _ = access.version(db, ctx, other.document_version_id)
        if other_doc.id != doc.id:
            access.fail("NOT_FOUND", "Related assessment not found.", status=404)
    row = FindingAnnotation(
        finding_id=finding.id,
        action=payload.action,
        note=payload.note,
        related_new_assessment_id=str(payload.related_new_assessment_id)
        if payload.related_new_assessment_id
        else None,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(row)
    record(
        db,
        ctx,
        "DOCUMENT_FINDING_ANNOTATED",
        doc,
        version,
        {"finding_id": finding.id, "action": payload.action},
    )
    return {**result(row, doc), "finding_outcome": finding.outcome}
