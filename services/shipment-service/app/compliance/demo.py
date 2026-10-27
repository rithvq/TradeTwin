"""Internal SIMULATION harness. Uses the real review, binding, evaluation and dispatch services."""

import hashlib
from datetime import date, timedelta
from io import BytesIO
from textwrap import wrap

from sqlalchemy import select

from app.document_desk import mapping, register, review
from app.document_desk import schemas as ds
from app.document_desk.ledger import flatten
from app.document_desk.models import (
    Attempt,
    Document,
    Job,
    TrustedKey,
    VerificationCheck,
    VerificationResult,
)
from app.operations.models import Assignment, Attachment, Consignment, ConsignmentItem
from app.trades.models import Trade, User, now, uid
from app.trades.transactions import Context

from . import (
    bindings,
    context,
    dispatch,
    evaluations,
    facts,
    governance,
    reviews,
    templates,
    turnover,
)
from .models import Binding, Pack
from .schemas_dispatch import Acknowledge, AuthorizationInput, PacketPrepare, ReleaseDecision
from .schemas_facts import (
    BindingPrepare,
    DeclarationReview,
    EvaluationInput,
    FactPrepare,
    IdentityInput,
    ManifestPrepare,
    TransportInput,
    TurnoverInput,
)
from .schemas_rules import PackReview, PackTestInput, PublishInput, SourceInput


def pdf(text):
    from reportlab.pdfgen.canvas import Canvas

    output = BytesIO()
    page = Canvas(output)
    rows = [part for line in text.splitlines() for part in (wrap(line, 94) or [""])]
    for start in range(0, max(1, len(rows)), 45):
        page.setFont("Helvetica-Bold", 10)
        page.drawString(40, 800, "TradeTwin SIMULATION ONLY - not a government-issued record")
        page.setFont("Courier", 9)
        for index, line in enumerate(rows[start : start + 45]):
            page.drawString(40, 770 - index * 16, line)
        page.showPage()
    page.save()
    return output.getvalue()


def actor(db, fx, role):
    side = (
        "carrier"
        if role.startswith("carrier") or role.startswith("driver")
        else "buyer"
        if role.startswith("buyer")
        else "seller"
    )
    return Context(db.get(User, fx["users"][role]), fx["organizations"][side], uid())


def attachment(db, ctx, trade, cn, label, content, store=None, purpose="DOCUMENT_FINANCIAL"):
    if store:
        return store(db, ctx, trade, cn, label, content, purpose)
    row = Attachment(
        trade_id=trade.id,
        consignment_id=cn.id if cn else None,
        uploaded_by_organization_id=ctx.org_id,
        original_name=label,
        object_key="SIMULATION_TEST_METADATA_ONLY/" + uid(),
        content_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        security_state="CLEAN",
        purpose=purpose,
        finalised_at=now(),
        created_by=ctx.user.id,
    )
    db.add(row)
    db.flush()
    return row


def document(db, ctx, trade, cn, kind, canonical, store=None):
    content = pdf("\n".join(f"{path}: {value}" for path, value in flatten(canonical).items()))
    a = attachment(
        db,
        ctx,
        trade,
        cn,
        kind.lower() + ".pdf",
        content,
        store,
        "DOCUMENT_FINANCIAL" if kind == "TAX_INVOICE" else "OTHER",
    )
    result = register.create(
        db,
        ctx,
        trade.id,
        ds.Registration(
            document_type=kind,
            label="PH4 simulated " + kind,
            trade_id=trade.id,
            initial_consignment_id=cn.id,
            primary_attachment_id=a.id,
            visibility="OWNER_ONLY"
            if kind
            in {
                "VEHICLE_RC",
                "VEHICLE_INSURANCE",
                "FITNESS_CERTIFICATE",
                "PUC_CERTIFICATE",
                "GOODS_PERMIT",
                "PERMIT_AUTHORISATION",
                "DRIVER_LICENCE",
                "CARGO_INSURANCE",
            }
            else "TRADE_PARTIES",
        ),
    )
    doc = db.get(Document, result["id"])
    for line in canonical.get("lines", []):
        issued = review.issue_line(
            db, ctx, doc.current_version_id, ds.Reason(reason="Simulation source line")
        )
        line["document_line_ref"] = issued["id"]
    canonical = ds.CanonicalDocument.model_validate(canonical).model_dump(mode="json")
    ctx.if_match = f'"{doc.row_version}"'
    draft = review.save(
        db,
        ctx,
        doc.current_version_id,
        ds.FactRevisionInput(
            canonical_document=canonical,
            field_decisions=[
                {
                    "field_path": k,
                    "decision": "CORRECTED",
                    "effective_value": v,
                    "provenance": "HUMAN_TRANSCRIPTION",
                    "reason": "Explicit synthetic fixture transcription",
                    "source_locator": {"source_attachment_id": a.id},
                }
                for k, v in flatten(canonical).items()
            ],
        ),
    )
    ctx.if_match = f'"{doc.row_version}"'
    review.submit(db, ctx, draft["id"], ds.Submission(content_hash=draft["content_hash"]))
    return doc, a, canonical


def source_pack(db, fx, trade, store=None):
    from app.trades.context_locks import registry_lock

    registry_lock(db, True)
    author, publisher = actor(db, fx, "seller-operations"), actor(db, fx, "seller-approver")
    existing = db.scalar(
        select(Pack).where(Pack.family_code == templates.FAMILY, Pack.environment == "SIMULATION")
    )
    if existing:
        return existing
    a = attachment(
        db,
        author,
        trade,
        None,
        "phase4-source.pdf",
        pdf(
            "Synthetic source snapshot for deterministic review tests.\n"
            "No claim of live governmental validation."
        ),
        store,
        "OTHER",
    )
    # Encrypted storage commits the upload before network I/O. Reacquire the
    # registry lock and recheck so concurrent profile demos cannot publish two packs.
    registry_lock(db, True)
    existing = db.scalar(
        select(Pack).where(Pack.family_code == templates.FAMILY, Pack.environment == "SIMULATION")
    )
    if existing:
        return existing
    source = governance.source(
        db,
        author,
        None,
        SourceInput(
            source_status="ACTIVE",
            source_origin="SIMULATION_FIXTURE",
            source_kind="RULE",
            issuer="TradeTwin simulation fixture",
            title="Simulation-only ordinary movement rules",
            official_url="https://gstcouncil.gov.in/node/4365",
            retrieved_at=now() - timedelta(seconds=1),
            snapshot_attachment_id=a.id,
            source_sha256=a.sha256,
            jurisdictions=["IN"],
            interpretation_note=(
                "SIMULATION FIXTURE. Source content is synthetic; production "
                "publication requires independently reviewed official snapshots."
            ),
        ),
    )
    pack = governance.create_pack(db, author, None, templates.candidate([source["id"]]))
    tested = governance.test_pack(
        db,
        author,
        pack["id"],
        PackTestInput(pack_hash=pack["content_hash"], test_suite_id="PH4_REQUIRED_BOUNDARIES_V1"),
    )
    approved = governance.review_pack(
        db,
        publisher,
        pack["id"],
        PackReview(
            pack_hash=pack["content_hash"],
            passed_test_run_id=tested["id"],
            reason="Independent review of explicitly simulated test fixture",
        ),
    )
    governance.publish(
        db,
        publisher,
        pack["id"],
        PublishInput(pack_hash=pack["content_hash"], review_approval_event_id=approved["id"]),
    )
    return db.get(Pack, pack["id"])


def observations(db, ctx, doc, canonical, values, kind, extra=None):
    from app.document_desk.context import input_context
    from app.trades.terms import digest

    from .clock import instant

    configuration = {
        "target_identifier": values.get("identifier"),
        "input_context": input_context(db, doc),
    }
    job = Job(
        document_version_id=doc.current_version_id,
        stage="VERIFY",
        status="SUCCEEDED",
        input_fingerprint=uid().replace("-", "") * 2,
        pipeline_version="PH4_SIMULATION_ONLY",
        schema_version="PH4_CANONICAL_V2",
        configuration_hash="0" * 64,
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json={},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    attempt = Attempt(
        job_id=job.id,
        attempt_number=1,
        worker_reference="PH4_SIMULATION_ONLY",
        lease_token=uid(),
        heartbeat_at=now(),
        status="SUCCEEDED",
    )
    db.add(attempt)
    db.flush()
    check = VerificationCheck(
        document_version_id=doc.current_version_id,
        fact_revision_id=doc.effective_fact_revision_id,
        job_id=job.id,
        check_type=kind,
        input_hash=digest(configuration),
        request_configuration_json=configuration,
        requested_by_user_id=ctx.user.id,
    )
    db.add(check)
    db.flush()
    row = VerificationResult(
        verification_check_id=check.id,
        job_attempt_id=attempt.id,
        result_json={
            "method": "SIMULATED",
            "provider_environment": "SIMULATION",
            "lookup_outcome": "RESULT_RETURNED",
            "signature_integrity": "NOT_CHECKED",
            "issuer_trust": "NOT_CHECKED",
            "identifier_match": "MATCH",
            "covered_field_paths": [],
            "provider_observed_at": instant(db).isoformat(),
            "checked_at": instant(db).isoformat(),
            "fresh_until": (instant(db) + timedelta(minutes=15)).isoformat(),
            "normalised_result": values,
            "limitations": [
                "Explicit seeded synthetic observation; never a live provider response."
            ],
            **(extra or {}),
        },
    )
    db.add(row)
    db.flush()
    return row


def prepare(db, fx, cn_id, store=None, wrong_vehicle=False, omit_ewb=False):
    trade = db.get(Trade, fx["trade_id"])
    if trade.execution_mode != "SIMULATION":
        from app.operations.access import fail

        fail(
            "FORBIDDEN",
            "Internal simulated observations cannot be created for production trades.",
            status=403,
        )
    cn = db.get(Consignment, cn_id)
    assignment = db.get(Assignment, cn.active_assignment_id)
    preparer, reviewer, carrier, carrier_reviewer = (
        actor(db, fx, r)
        for r in ("seller-operations", "seller-approver", "carrier-dispatcher", "carrier-reviewer")
    )
    source_pack(db, fx, trade, store)
    inherited = context.inherited(db, trade, cn)
    items = list(db.scalars(select(ConsignmentItem).where(ConsignmentItem.consignment_id == cn.id)))
    unit = "100000" if "PHASE4" in trade.reference else "10000"
    taxable = sum(int(i.allocated_quantity) * int(unit) for i in items)
    total, tax = taxable + taxable * 18 // 100, taxable * 18 // 100
    day = date.today().isoformat()
    invoice = {
        "schema_version": "PH4_CANONICAL_V2",
        "header": {
            "document_number": "D-" + cn.id[:8],
            "issue_date": day,
            "currency": "INR",
            "irn": hashlib.sha256(cn.id.encode()).hexdigest(),
            "acknowledgment_at": now().isoformat(),
            "place_of_supply_state_code": "33",
            "reverse_charge_position": "NO",
            "issuance_form": "ELECTRONIC_IT_ACT_DECLARED",
            "invoice_series_fy": turnover.fiscal_year(date.fromisoformat(day)),
            "invoice_profile_code": "ORDINARY_V1",
        },
        "parties": {
            "supplier": {
                "gstin": inherited["seller_gstin"],
                "legal_name": "Simulated seller",
                "address": {
                    k: v
                    for k, v in cn.pickup_address_snapshot.items()
                    if k in ds.PartialAddress.model_fields
                },
            },
            "recipient": {
                "gstin": inherited["buyer_gstin"],
                "legal_name": "Simulated buyer",
                "address": {
                    k: v
                    for k, v in cn.delivery_address_snapshot.items()
                    if k in ds.PartialAddress.model_fields
                },
            },
        },
        "lines": [
            {
                "document_line_ref": uid(),
                "description": "Cotton shirts",
                "hsn_code": "6109",
                "quantity": str(i.allocated_quantity),
                "uqc": i.uqc,
                "taxable_value_minor": str(int(i.allocated_quantity) * int(unit)),
                "declared_igst_rate_percent": "18",
                "igst_amount_minor": str(int(i.allocated_quantity) * int(unit) * 18 // 100),
            }
            for i in items
        ],
        "totals": {
            "taxable_subtotal_minor": str(taxable),
            "igst_total_minor": str(tax),
            "grand_total_minor": str(total),
        },
    }
    doc, asset, invoice = document(db, preparer, trade, cn, "TAX_INVOICE", invoice, store)
    preparer.if_match = f'"{doc.row_version}"'
    mapping.save(
        db,
        preparer,
        doc.id,
        ds.MappingInput(
            fact_revision_id=doc.effective_fact_revision_id,
            accepted_trade_revision_id=trade.accepted_revision_id,
            mappings=[
                {
                    "document_line_ref": line["document_line_ref"],
                    "trade_line_ref": item.line_ref,
                    "target_kind": "CONSIGNMENT_ITEM",
                    "consignment_item_id": item.id,
                    "mapped_quantity": str(item.allocated_quantity),
                    "uqc": item.uqc,
                }
                for line, item in zip(invoice["lines"], items, strict=True)
            ],
        ),
    )
    identity = turnover.identity(
        db,
        preparer,
        preparer.org_id,
        IdentityInput(
            pan=inherited["seller_gstin"][2:12], reason="Synthetic PAN, not a real taxpayer"
        ),
    )
    current_fy = turnover.fiscal_year(date.fromisoformat(day))
    declaration = turnover.prepare(
        db,
        preparer,
        preparer.org_id,
        TurnoverInput(
            pan_identity_reference=identity["id"],
            assessment_invoice_date=day,
            relevant_financial_years=[
                {
                    "financial_year_start": y,
                    "existence_status": "IN_EXISTENCE",
                    "pan_aggregate_turnover_minor": "6000000000"
                    if y == current_fy - 2
                    else "4000000000",
                    "provenance": "SELF_DECLARED",
                }
                for y in range(2017, current_fy)
            ],
            history_completeness_declared=True,
            supplier_exclusion_code="NONE_CLAIMED",
            declaration_note="Explicit simulated PAN aggregate history",
        ),
    )
    turnover.review(
        db,
        reviewer,
        declaration["id"],
        DeclarationReview(
            decision="APPROVE_DECLARATION", reason="Independent simulated declaration review"
        ),
    )
    preparer.if_match = f'"{context.version(db, trade.id)}"'
    fact = facts.prepare(
        db,
        preparer,
        cn.id,
        FactPrepare(
            expected_context_version=context.version(db, trade.id),
            submit_for_review=True,
            facts={
                "scope_profile_code": "ORDINARY_TAXABLE_INTERSTATE_ROAD_SALE",
                "declared_transit_state_codes": [],
                "corridor_declaration_basis": "CARRIER_DECLARATION",
                "requested_pickup_at": now().isoformat(),
                "requested_departure_at": now().isoformat(),
                "expected_arrival_at": (now() + timedelta(hours=4)).isoformat(),
                "seller_taxpayer_category_code": "REGULAR",
                "recipient_category_code": "REGISTERED_REGULAR",
                "supply_taxability": "TAXABLE",
                "commodity_scope_codes": ["ORDINARY_COTTON_SHIRTS"],
                "over_dimensional_cargo_declared": False,
                "special_valuation_profile": "NONE_DECLARED",
                "reverse_charge_position": "NO",
                "document_issue_scenario": "ONE_INVOICE_PER_CONSIGNMENT",
                "seller_turnover_declaration_id": declaration["id"],
            },
        ),
    )
    facts.review(
        db,
        reviewer,
        fact["id"],
        DeclarationReview(
            decision="APPROVE_DECLARATION", reason="Independent simulation fact review"
        ),
    )
    preparer.if_match = f'"{context.version(db, trade.id)}"'
    manifest = facts.manifest(
        db,
        preparer,
        cn.id,
        ManifestPrepare(
            expected_context_version=context.version(db, trade.id),
            manifest={
                "items": [
                    {
                        "consignment_item_id": i.id,
                        "trade_line_ref": i.line_ref,
                        "loaded_quantity": str(i.allocated_quantity),
                        "uqc": i.uqc,
                    }
                    for i in items
                ],
                "actual_prepared_gross_weight_kg": "400",
                "actual_prepared_package_count": 4,
                "package_type": "CARTON",
                "measurement_basis": "DECLARED",
            },
        ),
    )
    documents = [doc]
    selected_observations = []
    for gstin in (inherited["seller_gstin"], inherited["buyer_gstin"]):
        selected_observations.append(
            observations(
                db,
                preparer,
                doc,
                invoice,
                {"identifier": gstin, "status": "ACTIVE"},
                "GSTIN_AUTHORITY_LOOKUP",
            ).id
        )
    selected_observations.append(
        observations(
            db,
            preparer,
            doc,
            invoice,
            {"identifier": invoice["header"]["irn"], "status": "ACTIVE"},
            "IRN_LIVE_STATUS",
        ).id
    )
    # These fixtures are offline cryptographic checks, not authority-status assertions.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    trusted = TrustedKey(
        issuer="TradeTwin simulation only",
        key_purpose="IRP_SIGNATURE",
        provider_environment="SIMULATION",
        key_identifier=uid(),
        key_fingerprint=hashlib.sha256(public.encode()).hexdigest(),
        algorithm="RS256",
        public_key_reference=public,
        official_source_url="https://example.invalid/simulation",
        registry_policy_version="PH4_SIMULATION_V1",
    )
    db.add(trusted)
    db.flush()
    signed = observations(
        db,
        preparer,
        doc,
        invoice,
        {},
        "IRP_JSON_SIGNATURE",
        {
            "method": "SIMULATED_SIGNATURE_CHECK",
            "signature_integrity": "VALID",
            "issuer_trust": "TRUSTED_FOR_THIS_CHECK",
            "trusted_key_id": trusted.id,
            "covered_field_paths": [
                "header.irn",
                "header.document_number",
                "header.issue_date",
                "parties.supplier.gstin",
                "parties.recipient.gstin",
                "totals.grand_total_minor",
            ],
            "normalised_result": {"signed_document": invoice},
        },
    )
    selected_observations.append(signed.id)
    if not omit_ewb:
        number = str(int(hashlib.sha256(cn.id.encode()).hexdigest()[:10], 16)).zfill(12)[-12:]
        vehicle = (
            "WRONG-VEHICLE" if wrong_vehicle else assignment.vehicle_snapshot["registration_number"]
        )
        expiry = (now() + timedelta(days=1)).isoformat()
        ewb = {
            "header": {"document_number": number, "issue_date": day},
            "eway_bill": {
                "eway_bill_number": number,
                "part_information": "FULL_COPY",
                "referenced_document_number": invoice["header"]["document_number"],
                "referenced_document_date": day,
                "declared_invoice_value_minor": str(total),
                "vehicle_registration_number": vehicle,
                "valid_from_at": (now() - timedelta(minutes=5)).isoformat(),
                "valid_until_at": expiry,
                "generated_at": now().isoformat(),
            },
            "packing_transport": {"transport_mode_declared": "ROAD"},
        }
        ewb_doc, _, ewb = document(db, preparer, trade, cn, "EWAY_BILL_COPY", ewb, store)
        documents.append(ewb_doc)
        selected_observations.append(
            observations(
                db,
                preparer,
                ewb_doc,
                ewb,
                {
                    "identifier": number,
                    "status": "ACTIVE",
                    "document_number": invoice["header"]["document_number"],
                    "document_date": day,
                    "invoice_value_minor": str(total),
                    "vehicle_registration_number": vehicle,
                    "supplier_gstin": inherited["seller_gstin"],
                    "recipient_gstin": inherited["buyer_gstin"],
                    "transport_mode": "ROAD",
                    "part_information": "FULL_COPY",
                    "valid_until": expiry,
                },
                "EWB_AUTHORITY_LOOKUP",
            ).id
        )
    transport_ids, permit = [], None
    for kind in (
        "VEHICLE_RC",
        "VEHICLE_INSURANCE",
        "FITNESS_CERTIFICATE",
        "PUC_CERTIFICATE",
        "GOODS_PERMIT",
        "PERMIT_AUTHORISATION",
        "DRIVER_LICENCE",
    ):
        transport_doc, _, _ = document(
            db,
            carrier,
            trade,
            cn,
            kind,
            {"header": {"document_number": kind + "-" + cn.id[:8], "issue_date": day}},
            store,
        )
        evidence = facts.transport(
            db,
            carrier,
            cn.id,
            TransportInput(
                subject_type="DRIVER" if kind == "DRIVER_LICENCE" else "VEHICLE",
                subject_id=assignment.driver_user_id
                if kind == "DRIVER_LICENCE"
                else assignment.vehicle_id,
                assignment_id=assignment.id,
                evidence_type=kind,
                document_version_id=transport_doc.current_version_id,
                reviewed_fact_revision_id=transport_doc.effective_fact_revision_id,
                document_number=kind + "-" + cn.id[:8],
                issuing_authority="SIMULATION ONLY",
                source_mode="ORIGINAL_DOCUMENT",
                valid_from=now() - timedelta(days=1),
                valid_until=now() + timedelta(days=30),
                covered_vehicle_number=assignment.vehicle_snapshot["registration_number"],
                covered_driver_reference=assignment.driver_user_id,
                covered_vehicle_classes=[assignment.vehicle_snapshot["vehicle_type"]],
                covered_states=["29", "33"],
                permit_basis="NATIONAL",
                route_restriction_position="NONE_DECLARED",
                parent_permit_evidence_revision_id=permit
                if kind == "PERMIT_AUTHORISATION"
                else None,
            ),
        )
        facts.transport_review(
            db,
            carrier_reviewer,
            evidence["id"],
            DeclarationReview(
                decision="APPROVE_DECLARATION",
                reason="Independent simulated transport source review",
            ),
        )
        transport_ids.append(evidence["id"])
        if kind == "GOODS_PERMIT":
            permit = evidence["id"]

    def reference(d):
        return {
            "document_id": d.id,
            "document_version_id": d.current_version_id,
            "reviewed_fact_revision_id": d.effective_fact_revision_id,
            "mapping_revision_id": d.current_mapping_revision_id,
            "canonical_document_id": d.canonical_document_id or d.id,
        }

    preparer.if_match = f'"{context.version(db, trade.id)}"'
    bound = bindings.prepare(
        db,
        preparer,
        cn.id,
        BindingPrepare(
            expected_context_version=context.version(db, trade.id),
            bindings={
                "compliance_fact_revision_id": fact["id"],
                "loading_manifest_revision_id": manifest["id"],
                "seller_turnover_declaration_id": declaration["id"],
                "movement_document": reference(doc),
                "supporting_documents": [reference(d) for d in documents[1:]],
                "verification_result_ids": selected_observations,
                "transport_evidence_revision_ids": transport_ids,
            },
        ),
    )
    return {
        "binding_id": bound["id"],
        "manifest_id": manifest["id"],
        "invoice_attachment_id": asset.id,
        "invoice_document_id": doc.id,
    }


def authorise(db, fx, cn_id, action, evaluation_id=None):
    preparer, reviewer = actor(db, fx, "seller-operations"), actor(db, fx, "seller-approver")
    cn, trade = db.get(Consignment, cn_id), db.get(Trade, fx["trade_id"])
    assignment = db.get(Assignment, cn.active_assignment_id)
    preparer.if_match = f'"{context.version(db, trade.id)}"'
    if evaluation_id is None:
        queued = evaluations.request(
            db,
            preparer,
            cn.id,
            EvaluationInput(action=action, expected_context_version=context.version(db, trade.id)),
        )
        evaluation = evaluations.complete(db, preparer, queued["evaluation_id"])
    else:
        evaluation, _, _, _ = evaluations.exact(
            db, preparer, evaluation_id, "compliance.evaluate", True
        )
        if (
            evaluation.consignment_id != cn.id
            or evaluation.action != action
            or evaluation.job_state != "COMPLETED"
        ):
            from app.operations.access import fail

            fail("COMPLIANCE_NOT_READY", "Use the completed evaluation for this exact demo action.")
    if evaluation.decision != "ELIGIBLE_FOR_REVIEW":
        import json

        from app.trades.errors import TradeError

        raise TradeError(
            "COMPLIANCE_NOT_READY", json.dumps(evaluations.read(db, preparer, evaluation.id)), 409
        )
    approval = reviews.release(
        db,
        reviewer,
        evaluation.id,
        ReleaseDecision(
            decision="APPROVE_RELEASE",
            evaluation_hash=evaluation.evaluation_hash,
            reason="Independent simulated release review",
        ),
    )
    bound = db.get(Binding, evaluation.binding_revision_id)
    requirements = evaluations.read(db, preparer, evaluation.id)["requirements"]
    carry_id = next(r["id"] for r in requirements if r["requirement_code"] == "CARRIED_DOCUMENTS")
    selected = [
        {
            "requirement_id": carry_id,
            "representation_type": "PAPER_INVOICE_REFERENCE",
            "source_reference": {
                "document_version_id": bound.binding_json["movement_document"][
                    "document_version_id"
                ]
            },
            "carry_method": "PAPER_COPY",
        }
    ]
    for ref in bound.binding_json["supporting_documents"]:
        if db.get(Document, ref["document_id"]).document_type == "EWAY_BILL_COPY":
            selected.append(
                {
                    "requirement_id": carry_id,
                    "representation_type": "EWB_NUMBER",
                    "source_reference": {"document_version_id": ref["document_version_id"]},
                    "carry_method": "EWB_NUMBER_AVAILABLE",
                }
            )
    packet = dispatch.prepare_packet(
        db,
        preparer,
        cn.id,
        PacketPrepare(
            action=action,
            evaluation_id=evaluation.id,
            evaluation_hash=evaluation.evaluation_hash,
            approval_id=approval["id"],
            selected_representations=selected,
        ),
    )
    driver_role = next(
        role
        for role in ("driver-one", "driver-two")
        if fx["users"][role] == assignment.driver_user_id
    )
    ack = dispatch.acknowledge(
        db,
        actor(db, fx, driver_role),
        packet["id"],
        Acknowledge(
            packet_hash=packet["packet_hash"],
            assignment_id=assignment.id,
            possession_confirmed=True,
            carry_methods=list({i["carry_method"] for i in packet["items"]}),
        ),
    )
    preparer.if_match = f'"{context.version(db, trade.id)}"'
    token = dispatch.issue(
        db,
        preparer,
        cn.id,
        AuthorizationInput(
            action=action,
            evaluation_id=evaluation.id,
            evaluation_hash=evaluation.evaluation_hash,
            approval_id=approval["id"],
            packet_id=packet["id"],
            packet_hash=packet["packet_hash"],
            acknowledgment_id=ack["id"],
            expected_context_version=context.version(db, trade.id),
        ),
    )
    return token
