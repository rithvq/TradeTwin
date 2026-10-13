from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from app.operations.access import exists, fail
from app.operations.models import Attachment
from app.trades.errors import TradeError
from app.trades.models import Trade
from app.trades.terms import digest

from . import access, checks, graph, verification
from .context import mapping_freshness
from .ledger import result
from .models import (
    AccessGrant,
    Artifact,
    Assessment,
    Asset,
    Attempt,
    Document,
    Extraction,
    FactRevision,
    FieldDecision,
    FileMetadata,
    FindingAnnotation,
    Job,
    LineMapping,
    ManualAttestation,
    MappingRevision,
    Observation,
    ReviewDecision,
    SubjectLink,
    VerificationCheck,
    Version,
)


def document_view(db, ctx, doc, selected_version=None):
    access.document(db, ctx, doc.id)
    db.flush()
    version = selected_version or db.get(Version, doc.current_version_id)
    assets = [
        result(a) for a in db.scalars(select(Asset).where(Asset.document_version_id == version.id))
    ]
    states = [db.get(Attachment, a["attachment_id"]).security_state for a in assets]
    security = (
        "CLEAN"
        if states and all(s == "CLEAN" for s in states)
        else "REJECTED"
        if "REJECTED" in states
        else "QUARANTINED"
    )
    extraction = db.scalar(
        select(Extraction)
        .where(Extraction.document_version_id == version.id)
        .order_by(Extraction.created_at.desc())
    )
    job = db.scalar(
        select(Job).where(Job.document_version_id == version.id).order_by(Job.created_at.desc())
    )
    reviewed = (
        db.scalar(
            select(ReviewDecision)
            .where(ReviewDecision.fact_revision_id == doc.effective_fact_revision_id)
            .order_by(ReviewDecision.created_at.desc())
        )
        if doc.effective_fact_revision_id
        else None
    )
    capture = access.full_capture(db, ctx, doc)
    if selected_version and selected_version.id != doc.current_version_id:
        reviewed = db.scalar(
            select(ReviewDecision)
            .join(FactRevision)
            .where(FactRevision.document_version_id == version.id)
            .order_by(ReviewDecision.created_at.desc())
        )
    assessments = []
    for row in db.scalars(
        select(Assessment)
        .where(Assessment.document_version_id == version.id)
        .order_by(Assessment.created_at.desc())
    ):
        try:
            assessments.append(checks.assessment_view(db, ctx, row))
        except TradeError:
            continue
    current = next((a for a in assessments if a["freshness"] == "CURRENT"), None)
    verifications = [
        verification.check_view(db, ctx, c)
        for c in db.scalars(
            select(VerificationCheck).where(VerificationCheck.document_version_id == version.id)
        )
    ]
    latest_results = [
        r for check in verifications for r in check["results"] if r["freshness"] == "CURRENT"
    ]
    signatures = [
        r["result_json"].get("signature_integrity", "NOT_CHECKED")
        for r in latest_results
        if r["result_json"].get("signature_integrity", "NOT_CHECKED") != "NOT_CHECKED"
    ]
    identity_id = doc.effective_fact_revision_id or (
        doc.latest_draft_fact_revision_id if capture else None
    )
    identity_fact = db.get(FactRevision, identity_id) if identity_id else None
    if identity_fact and identity_fact.document_version_id != version.id:
        identity_fact = None
    captured = identity_fact.canonical_document_json if identity_fact else {}
    lookups = [
        r["result_json"].get("lookup_outcome", "NOT_CHECKED")
        for r in latest_results
        if r["result_json"].get("lookup_outcome", "NOT_CHECKED") != "NOT_CHECKED"
    ]
    return {
        **result(doc),
        "latest_draft_fact_revision_id": doc.latest_draft_fact_revision_id
        if capture
        else doc.effective_fact_revision_id,
        "latest_job_id": job.id if job and capture else None,
        "current_version": {**result(version), "assets": assets},
        "versions": [
            result(v)
            for v in db.scalars(
                select(Version)
                .where(Version.document_id == doc.id)
                .order_by(Version.version_number)
            )
            if capture or v.id == doc.current_version_id
        ],
        "status_dimensions": {
            "file_security": security,
            "processing_job": job.status if job else None,
            "extraction": extraction.status if extraction else "NOT_STARTED",
            "human_review": "IN_REVIEW"
            if capture
            and version.id == doc.current_version_id
            and doc.latest_draft_fact_revision_id != doc.effective_fact_revision_id
            and doc.latest_draft_fact_revision_id
            else reviewed.review_state
            if reviewed
            else "IN_REVIEW"
            if doc.latest_draft_fact_revision_id
            else "UNREVIEWED",
            "data_consistency": current["consistency"] if current else "NOT_ASSESSED",
            "signature_integrity": signatures[-1] if signatures else "NOT_CHECKED",
            "issuer_trust": latest_results[-1]["result_json"].get("issuer_trust", "NOT_CHECKED")
            if latest_results
            else "NOT_CHECKED",
            "authority_lookup": lookups[-1] if lookups else "NOT_CHECKED",
            "freshness": "STALE" if assessments and not current else "CURRENT",
            "dispatch_readiness": "NOT_ASSESSED",
        },
        "linked_subjects": [
            result(s)
            for s in db.scalars(
                select(SubjectLink).where(
                    SubjectLink.document_version_id == version.id, SubjectLink.revoked_at.is_(None)
                )
            )
        ],
        "assessments": [{k: v for k, v in a.items() if k != "findings"} for a in assessments],
        "verification_checks": verifications,
        "allowed_actions": access.allowed(db, ctx, doc),
        "document_total_aggregation": "ALIAS_EXCLUDED"
        if doc.canonical_document_id
        else "ONCE_PER_DOCUMENT",
        "registration_declarations_are_not_verified_facts": True,
        "captured_identity": {
            "document_number": (captured.get("header") or {}).get("document_number"),
            "issue_date": (captured.get("header") or {}).get("issue_date"),
            "issuer_name": ((captured.get("parties") or {}).get("supplier") or {}).get(
                "legal_name"
            ),
        },
        "mapping_summary": mapped_summary(db, ctx, doc),
    }


def register(db, ctx, trade_id, kind=None, status=None, cursor=None):
    trade = exists(db, Trade, trade_id)
    # A trade-scoped permission is checked even for an empty register.
    side = access.participant_role(db, trade.id, ctx.org_id)
    if not side:
        fail("NOT_FOUND", "Trade not found.", status=404)
    access.require(db, ctx.user, ctx.org_id, "document.read", trade.id, side)
    query = (
        select(Document)
        .where(Document.trade_id == trade.id)
        .order_by(Document.created_at, Document.id)
    )
    if kind:
        query = query.where(Document.document_type == kind)
    if cursor:
        previous = exists(db, Document, cursor)
        access.document(db, ctx, previous.id)
        if previous.trade_id != trade.id:
            fail("NOT_FOUND", "Cursor not found.", status=404)
        from sqlalchemy import and_, or_

        query = query.where(
            or_(
                Document.created_at > previous.created_at,
                and_(Document.created_at == previous.created_at, Document.id > previous.id),
            )
        )
    rows = []
    for doc in db.scalars(query):
        if access.can_read(db, ctx, doc):
            body = document_view(db, ctx, doc)
            if (
                not status
                or status in body["status_dimensions"].values()
                or status == doc.lifecycle_status
                or status == doc.execution_mode
            ):
                rows.append(body)
            if len(rows) >= 51:
                break
    return {
        "items": rows[:50],
        "next_cursor": rows[49]["id"] if len(rows) > 50 else None,
        "allowed_actions": ["document.register"] if access.can_register(db, ctx, trade) else [],
        "execution_mode": trade.execution_mode,
    }


def manifest(db, ctx, ident):
    version, doc, _ = access.version(db, ctx, ident)
    assets = [
        result(a, doc)
        for a in db.scalars(select(Asset).where(Asset.document_version_id == version.id))
    ]
    artifacts = [
        result(a, doc)
        for a in db.scalars(select(Artifact).where(Artifact.document_version_id == version.id))
    ]
    facts = list(
        db.scalars(select(FactRevision).where(FactRevision.document_version_id == version.id))
    )
    if not access.full_capture(db, ctx, doc):
        facts = [f for f in facts if f.id == doc.effective_fact_revision_id]
    fact_ids = [f.id for f in facts]
    assessment_rows = []
    for assessment in db.scalars(
        select(Assessment).where(Assessment.document_version_id == version.id)
    ):
        try:
            assessment_rows.append(checks.assessment_view(db, ctx, assessment))
        except TradeError:
            continue
    body = {
        "schema_version": "PH3_EVIDENCE_MANIFEST_V1",
        "document_id": doc.id,
        "document_version_id": version.id,
        "source_manifest_hash": version.source_manifest_hash,
        "source_assets": assets,
        "derived_artifacts": artifacts if access.full_capture(db, ctx, doc) else [],
        "extraction_runs": [
            result(r, doc)
            for r in db.scalars(
                select(Extraction).where(Extraction.document_version_id == version.id)
            )
        ]
        if access.full_capture(db, ctx, doc)
        else [],
        "fact_revisions": [result(f, doc) for f in facts],
        "field_decisions": [
            result(d, doc)
            for d in db.scalars(
                select(FieldDecision).where(FieldDecision.fact_revision_id.in_(fact_ids))
            )
        ],
        "review_decisions": [
            result(d, doc)
            for d in db.scalars(
                select(ReviewDecision).where(ReviewDecision.fact_revision_id.in_(fact_ids))
            )
        ],
        "mappings": [
            result(m, doc)
            for m in db.scalars(
                select(MappingRevision).where(MappingRevision.document_version_id == version.id)
            )
        ],
        "assessments": assessment_rows,
        "verification_checks": [
            verification.check_view(db, ctx, c)
            for c in db.scalars(
                select(VerificationCheck).where(VerificationCheck.document_version_id == version.id)
            )
        ],
        "execution_mode": doc.execution_mode,
        "dispatch_readiness": "NOT_ASSESSED",
    }
    if access.full_capture(db, ctx, doc):
        runs = list(
            db.scalars(select(Extraction).where(Extraction.document_version_id == version.id))
        )
        job_ids = list(db.scalars(select(Job.id).where(Job.document_version_id == version.id)))
        body.update(
            observations=[
                result(o, doc)
                for o in db.scalars(
                    select(Observation).where(
                        Observation.extraction_run_id.in_([r.id for r in runs])
                    )
                )
            ],
            file_metadata=[
                result(m, doc)
                for m in db.scalars(
                    select(FileMetadata).where(FileMetadata.document_version_id == version.id)
                )
            ],
            processing_attempts=[
                result(a, doc)
                for a in db.scalars(select(Attempt).where(Attempt.job_id.in_(job_ids)))
            ],
            manual_attestations=[
                {**result(a, doc), "method": "MANUAL_REPORTED"}
                for a in db.scalars(
                    select(ManualAttestation).where(
                        ManualAttestation.document_version_id == version.id
                    )
                )
            ],
        )
    finding_ids = [f["id"] for a in assessment_rows for f in a["findings"]]
    body["finding_annotations"] = [
        result(a, doc)
        for a in db.scalars(
            select(FindingAnnotation).where(FindingAnnotation.finding_id.in_(finding_ids))
        )
    ]
    if doc.owner_organization_id == ctx.org_id:
        body["access_history"] = [
            result(a, doc)
            for a in db.scalars(
                select(AccessGrant).where(AccessGrant.document_version_id == version.id)
            )
        ]
        body["subject_link_history"] = [
            result(a, doc)
            for a in db.scalars(
                select(SubjectLink).where(SubjectLink.document_version_id == version.id)
            )
        ]
    body["manifest_hash"] = digest(body)
    return body


def context_view(db, ctx, consignment_id):
    trade, cn, side = access.consignment(db, ctx, consignment_id)
    links = list(
        db.scalars(
            select(SubjectLink).where(
                SubjectLink.subject_type == "CONSIGNMENT",
                SubjectLink.subject_id == cn.id,
                SubjectLink.revoked_at.is_(None),
            )
        )
    )
    refs, maps, findings, verification_refs = [], [], [], []
    for link in links:
        version = db.get(Version, link.document_version_id)
        doc = db.get(Document, version.document_id)
        if not access.can_read(db, ctx, doc):
            continue
        refs.append(
            {
                "document_id": doc.id,
                "version_id": version.id,
                "source_manifest_hash": version.source_manifest_hash,
                "document_type": doc.document_type,
                "canonical_document_id": doc.canonical_document_id,
            }
        )
        mapping = (
            db.get(MappingRevision, doc.current_mapping_revision_id)
            if doc.current_mapping_revision_id
            else None
        )
        if mapping:
            maps.append(
                {
                    "mapping_revision_id": mapping.id,
                    "freshness": mapping_freshness(db, doc, mapping.source_context_json),
                }
            )
        for assessment in db.scalars(
            select(Assessment).where(Assessment.document_version_id == version.id)
        ):
            try:
                viewed = checks.assessment_view(db, ctx, assessment)
                findings.extend(
                    [
                        {**f, "freshness": viewed["freshness"], "assessment_id": assessment.id}
                        for f in viewed["findings"]
                        if f["outcome"] in {"FAIL", "UNKNOWN"}
                    ]
                )
            except TradeError:
                continue
        verification_refs.extend(
            [
                {"check_id": c.id, "input_hash": c.input_hash}
                for c in db.scalars(
                    select(VerificationCheck).where(
                        VerificationCheck.document_version_id == version.id
                    )
                )
            ]
        )
    body = {
        "schema_version": 1,
        "consignment_id": cn.id,
        "accepted_revision_id": trade.accepted_revision_id,
        "linked_document_refs": refs,
        "effective_mapping_refs": maps,
        "relevant_findings": findings,
        "verification_observation_refs": verification_refs,
        "freshness": "STALE"
        if any(m["freshness"] == "STALE" for m in maps)
        or any(f["freshness"] == "STALE" for f in findings)
        else "CURRENT",
        "limitations": [
            "Accepted agreement and consignment facts remain the planning authority; "
            "document declarations cannot override them."
        ],
    }
    body["document_context_hash"] = digest(body)
    return body


def operational_projections(db, ctx, consignment_id):
    from app.operations.models import Assignment

    from .ledger import flatten

    rows = []
    for link in db.scalars(
        select(SubjectLink).where(
            SubjectLink.subject_type == "CONSIGNMENT",
            SubjectLink.subject_id == str(consignment_id),
            SubjectLink.revoked_at.is_(None),
        )
    ):
        version = db.get(Version, link.document_version_id)
        doc = db.get(Document, version.document_id)
        if version.id != doc.current_version_id or doc.document_type not in access.OPERATIONAL:
            continue
        try:
            access.document(db, ctx, doc.id, projection=True)
        except TradeError:
            continue
        fact = (
            db.get(FactRevision, doc.effective_fact_revision_id)
            if doc.effective_fact_revision_id
            else None
        )
        paths = set(access.OPERATIONAL_PATHS) if doc.owner_organization_id == ctx.org_id else set()
        for grant in db.scalars(
            select(AccessGrant).where(
                AccessGrant.document_version_id == version.id,
                AccessGrant.grantee_organization_id == ctx.org_id,
                AccessGrant.access_type == "OPERATIONAL_PROJECTION",
                AccessGrant.revoked_at.is_(None),
            )
        ):
            if access.active_assignment(db, ctx, db.get(Assignment, grant.assignment_id)):
                paths.update(grant.allowed_field_paths_json)
        fields = flatten(fact.canonical_document_json) if fact else {}
        if paths:
            rows.append(
                {
                    "document_id": doc.id,
                    "document_type": doc.document_type,
                    "fields": {
                        p: v for p, v in fields.items() if p in paths & access.OPERATIONAL_PATHS
                    },
                    "execution_mode": doc.execution_mode,
                    "dispatch_readiness": "NOT_ASSESSED",
                }
            )
    return rows


def summary(db, ctx, trade_id):
    listed = register(db, ctx, trade_id)
    signals = []
    for doc in listed["items"]:
        version_id = doc["current_version_id"]
        for assessment in db.scalars(
            select(Assessment).where(Assessment.document_version_id == version_id)
        ):
            try:
                view = checks.assessment_view(db, ctx, assessment)
            except TradeError:
                continue
            for finding in view["findings"]:
                if finding["outcome"] in {"FAIL", "UNKNOWN"}:
                    signals.append(
                        {
                            **finding,
                            "document_id": doc["id"],
                            "assessment_id": assessment.id,
                            "assessed_at": assessment.created_at.isoformat(),
                            "freshness": view["freshness"],
                            "signal_kind": "DOCUMENT_REVIEW_SIGNAL",
                            "not_fraud_conclusion": True,
                        }
                    )
        for dimension, state in doc["status_dimensions"].items():
            if state in {
                "FAILED",
                "CANCELLED",
                "INVALID",
                "KEY_UNAVAILABLE",
                "UNAVAILABLE",
                "NOT_CONFIGURED",
                "STALE",
                "PARTIAL",
            }:
                signals.append(
                    {
                        "id": f"{doc['id']}:{dimension}",
                        "document_id": doc["id"],
                        "check_code": dimension.upper(),
                        "outcome": state,
                        "severity": "REVIEW",
                        "message": f"{dimension.replace('_', ' ')}: {state}",
                        "freshness": doc["status_dimensions"]["freshness"],
                        "not_fraud_conclusion": True,
                    }
                )
    return {
        "documents": listed["items"],
        "signals": signals,
        "graph": graph.build(db, ctx, [db.get(Document, d["id"]) for d in listed["items"]]),
        "dispatch_readiness": "NOT_ASSESSED",
        "notice": "Document evidence available for Phase 4 evaluation.",
        "risk_signal_warning": "Document discrepancies are review signals, "
        "not automatic fraud conclusions.",
    }


def mapped_summary(db, ctx, doc):
    mapping = (
        db.get(MappingRevision, doc.current_mapping_revision_id)
        if doc.current_mapping_revision_id
        else None
    )
    totals = defaultdict(Decimal)
    for m in (
        db.scalars(select(LineMapping).where(LineMapping.mapping_revision_id == mapping.id))
        if mapping
        else []
    ):
        totals[m.document_line_ref] += m.mapped_quantity
    fact = (
        db.get(FactRevision, doc.effective_fact_revision_id)
        if doc.effective_fact_revision_id
        else None
    )
    return [
        {
            "document_line_ref": line["document_line_ref"],
            "mapped_quantity": str(totals[line["document_line_ref"]]),
            "unmapped_quantity": str(Decimal(line["quantity"]) - totals[line["document_line_ref"]])
            if line.get("quantity") is not None
            else None,
            "uqc": line.get("uqc"),
        }
        for line in (fact.canonical_document_json["lines"] if fact else [])
    ]
