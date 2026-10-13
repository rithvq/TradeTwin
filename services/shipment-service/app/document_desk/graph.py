"""Permission-filtered relational provenance projection; no duplicate graph ownership."""

from sqlalchemy import select

from app.trades.errors import TradeError
from app.trades.models import Trade

from . import access, checks
from .models import (
    Assessment,
    Asset,
    Extraction,
    FactRevision,
    FieldDecision,
    LineMapping,
    MappingRevision,
    Observation,
    Relationship,
    SubjectLink,
    VerificationCheck,
    VerificationResult,
    Version,
)


def build(db, ctx, documents):
    nodes, edges = {}, {}

    def node(ident, kind, label, href):
        nodes[ident] = {"id": ident, "type": kind, "label": label, "href": href}

    def connect(source, target, label):
        ident = f"{source}:{target}:{label}"
        edges[ident] = {"id": ident, "source": source, "target": target, "label": label}

    for doc in documents:
        version = db.get(Version, doc.current_version_id)
        path = f"/documents/versions/{version.id}"
        trade = db.get(Trade, doc.trade_id)
        node(doc.id, "DOCUMENT", doc.label, path + "/review")
        node(version.id, "DOCUMENT_VERSION", f"Source v{version.version_number}", path + "/review")
        connect(doc.id, version.id, "HAS_SOURCE_VERSION")
        if trade.accepted_revision_id:
            node(
                trade.accepted_revision_id,
                "TRADE_REVISION",
                "Accepted commercial revision",
                f"/trades/{trade.id}?revision={trade.accepted_revision_id}",
            )
            connect(trade.accepted_revision_id, version.id, "RECONCILED_WITH")
        for link in db.scalars(
            select(SubjectLink).where(
                SubjectLink.document_version_id == version.id,
                SubjectLink.subject_type == "CONSIGNMENT",
                SubjectLink.revoked_at.is_(None),
            )
        ):
            _, cn, _ = access.consignment(db, ctx, link.subject_id)
            node(
                cn.id,
                "CONSIGNMENT",
                cn.reference,
                f"/documents/trades/{trade.id}?consignment={cn.id}",
            )
            connect(cn.id, version.id, "SUPPORTED_BY")
        for asset in db.scalars(select(Asset).where(Asset.document_version_id == version.id)):
            node(
                asset.attachment_id,
                "ORIGINAL_FILE",
                f"Original {asset.asset_sha256[:12]}",
                path + "/evidence",
            )
            connect(version.id, asset.attachment_id, "USES_IMMUTABLE_FILE")
        capture = access.full_capture(db, ctx, doc)
        facts = list(
            db.scalars(select(FactRevision).where(FactRevision.document_version_id == version.id))
        )
        if not capture:
            facts = [f for f in facts if f.id == doc.effective_fact_revision_id]
        for fact in facts:
            node(
                fact.id,
                "FACT_REVISION",
                f"Captured snapshot {fact.revision_number}",
                path + f"/review?fact={fact.id}",
            )
            connect(version.id, fact.id, "CAPTURED_AS")
            for decision in db.scalars(
                select(FieldDecision).where(FieldDecision.fact_revision_id == fact.id)
            ):
                node(
                    decision.id,
                    "REVIEWED_FIELD",
                    f"{decision.decision}: {decision.field_path}",
                    path + f"/review?fact={fact.id}",
                )
                connect(decision.id, fact.id, "IN_REVIEW_SNAPSHOT")
                if decision.observation_id:
                    connect(
                        decision.observation_id,
                        decision.id,
                        "CORRECTED_FROM" if decision.decision == "CORRECTED" else "REVIEWED_FROM",
                    )
        if capture:
            for run in db.scalars(
                select(Extraction).where(Extraction.document_version_id == version.id)
            ):
                node(run.id, "EXTRACTION_RUN", run.engine_name, path + "/processing")
                connect(version.id, run.id, "PROCESSED_AS")
                for obs in db.scalars(
                    select(Observation).where(Observation.extraction_run_id == run.id)
                ):
                    node(
                        obs.id,
                        "FIELD_OBSERVATION",
                        obs.field_path,
                        path + f"/review?observation={obs.id}",
                    )
                    connect(run.id, obs.id, "OBSERVED")
                    connect(
                        obs.source_locator_json["source_attachment_id"], obs.id, "SOURCE_LOCATION"
                    )
        for mapping in db.scalars(
            select(MappingRevision).where(MappingRevision.document_version_id == version.id)
        ):
            if mapping.fact_revision_id not in nodes:
                continue
            node(
                mapping.id,
                "MAPPING_REVISION",
                "Confirmed line mappings",
                f"/documents/{doc.id}/mapping",
            )
            connect(mapping.fact_revision_id, mapping.id, "MAPPED_AS")
            for portion in db.scalars(
                select(LineMapping).where(LineMapping.mapping_revision_id == mapping.id)
            ):
                node(
                    portion.id,
                    "LINE_MAPPING",
                    f"{portion.mapped_quantity} {portion.uqc}",
                    f"/documents/{doc.id}/mapping",
                )
                connect(mapping.id, portion.id, "HAS_PORTION")
        for assessment in db.scalars(
            select(Assessment).where(Assessment.document_version_id == version.id)
        ):
            try:
                viewed = checks.assessment_view(db, ctx, assessment)
            except TradeError:
                continue
            node(
                assessment.id,
                "ASSESSMENT_RUN",
                f"{viewed['freshness']} / {len(viewed['findings'])} checks",
                path + f"/findings?assessment={assessment.id}",
            )
            connect(assessment.fact_revision_id, assessment.id, "ASSESSED_AS")
            for finding in viewed["findings"]:
                node(
                    finding["id"],
                    "FINDING",
                    f"{finding['check_code']}: {finding['outcome']}",
                    path + f"/findings?assessment={assessment.id}" + f"&finding={finding['id']}",
                )
                connect(assessment.fact_revision_id, finding["id"], "OBSERVED_INPUT")
                connect(assessment.id, finding["id"], "HAS_FINDING")
                expected = finding["expected_source_json"].get("id")
                if expected and expected in nodes:
                    connect(expected, finding["id"], "EXPECTED_INPUT")
                if assessment.mapping_revision_id:
                    connect(assessment.mapping_revision_id, finding["id"], "MAPPING_INPUT")
        for check in db.scalars(
            select(VerificationCheck).where(VerificationCheck.document_version_id == version.id)
        ):
            for observation in db.scalars(
                select(VerificationResult).where(
                    VerificationResult.verification_check_id == check.id
                )
            ):
                result = observation.result_json
                node(
                    observation.id,
                    "VERIFICATION_RESULT",
                    f"{check.check_type}: {result.get('signature_integrity', 'NOT_CHECKED')} / "
                    f"{result['lookup_outcome']}",
                    path + "/verification",
                )
                connect(version.id, observation.id, "AS_CHECKED_OBSERVATION")
    for relationship in db.scalars(select(Relationship)):
        if relationship.from_document_id in nodes and relationship.to_document_id in nodes:
            connect(
                relationship.from_document_id,
                relationship.to_document_id,
                relationship.relationship_type,
            )
    return {
        "nodes": list(nodes.values()),
        "edges": [e for e in edges.values() if e["source"] in nodes and e["target"] in nodes],
    }
