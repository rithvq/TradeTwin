from sqlalchemy import func, select

from app.operations.access import exists, fail
from app.trades.models import uid
from app.trades.terms import digest

from . import access
from .ledger import field_path, flatten, match, record, result, touch
from .models import (
    Asset,
    Extraction,
    FactRevision,
    FieldDecision,
    LineIdentity,
    Observation,
    Page,
    ReviewDecision,
    ReviewedLine,
)


def locator(db, version_id, source):
    data = source.model_dump(mode="json") if hasattr(source, "model_dump") else source
    if not db.scalar(
        select(Asset.id).where(
            Asset.document_version_id == version_id,
            Asset.attachment_id == data["source_attachment_id"],
        )
    ):
        fail("OBSERVATION_SOURCE_MISMATCH", "Source belongs to a different document version.")
    if data.get("page_number") and not db.scalar(
        select(Page.id).where(
            Page.document_version_id == version_id, Page.page_number == data["page_number"]
        )
    ):
        fail("OBSERVATION_SOURCE_MISMATCH", "Source page does not exist.")
    if data.get("text_end") is not None:
        from .models import Artifact

        artifact = db.get(Artifact, data.get("text_artifact_id"))
        if not artifact or artifact.document_version_id != version_id:
            fail("OBSERVATION_SOURCE_MISMATCH", "Text artifact does not belong to this source.")
        if data["text_end"] > artifact.transformation_metadata_json.get("character_count", 0):
            fail("OBSERVATION_SOURCE_MISMATCH", "Text span is outside the source artifact.")
    return data


def save(db, ctx, ident, payload):
    version, doc, _ = access.version(db, ctx, ident, "document.review", True)
    match(ctx, doc)
    if version.id != doc.current_version_id:
        fail("SOURCE_VERSION_CHANGED", "Review the current source version.")
    base = str(payload.base_fact_revision_id) if payload.base_fact_revision_id else None
    if base != doc.latest_draft_fact_revision_id:
        fail("REVIEW_HEAD_CHANGED", "Review draft changed. Reload its exact head.")
    run = exists(db, Extraction, payload.extraction_run_id) if payload.extraction_run_id else None
    if run and run.document_version_id != version.id:
        fail("OBSERVATION_SOURCE_MISMATCH", "Extraction belongs to another source version.")
    canonical = payload.canonical_document.model_dump(mode="json")
    for line in canonical["lines"]:
        identity = db.get(LineIdentity, line["document_line_ref"])
        if not identity or identity.document_version_id != version.id:
            fail(
                "OBSERVATION_SOURCE_MISMATCH", "Use a server-issued line identity for this source."
            )
    values = flatten(canonical)
    decisions = {d.field_path: d for d in payload.field_decisions}
    if len(decisions) != len(payload.field_decisions) or not set(values) <= set(decisions):
        fail(
            "OBSERVATION_SOURCE_MISMATCH",
            "Every captured non-null field needs one explicit provenance decision.",
        )
    old = db.get(FactRevision, base) if base else None
    old_lines = (
        {line["document_line_ref"] for line in old.canonical_document_json["lines"]}
        if old
        else set()
    )
    alignments = {str(a.document_line_ref): a.candidate_row_key for a in payload.line_alignments}
    if len(alignments) != len(payload.line_alignments) or len(set(alignments.values())) != len(
        alignments
    ):
        fail(
            "OBSERVATION_SOURCE_MISMATCH",
            "A source row cannot represent two reviewed line identities.",
        )
    if run and old and old.extraction_run_id != run.id:
        if any(line["document_line_ref"] not in alignments for line in canonical["lines"]):
            fail(
                "OBSERVATION_SOURCE_MISMATCH",
                "Re-extracted lines require explicit source-row alignment.",
            )
    number = (
        db.scalar(
            select(func.max(FactRevision.revision_number)).where(
                FactRevision.document_version_id == version.id
            )
        )
        or 0
    ) + 1
    revision = FactRevision(
        id=uid(),
        document_version_id=version.id,
        base_fact_revision_id=base,
        extraction_run_id=run.id if run else None,
        revision_number=number,
        canonical_document_json=canonical,
        content_hash="",
        created_by_user_id=ctx.user.id,
        created_by_organization_id=ctx.org_id,
    )
    decision_values = []
    for path, decision in decisions.items():
        try:
            valid = field_path(path)
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            fail("VALIDATION_ERROR", "Unknown canonical field path.", path, 422)
        actual = values.get(path)
        line_ref = path.split(".")[1] if path.startswith("lines.") else None
        if decision.document_line_ref and str(decision.document_line_ref) != line_ref:
            fail(
                "OBSERVATION_SOURCE_MISMATCH",
                "Decision line identity differs from its canonical field path.",
            )
        if actual != decision.effective_value:
            fail("VALIDATION_ERROR", "Decision and canonical value differ.", path, 422)
        observation = (
            exists(db, Observation, decision.observation_id) if decision.observation_id else None
        )
        if observation:
            if decision.provenance != "EXTRACTION_REVIEW":
                fail(
                    "OBSERVATION_SOURCE_MISMATCH",
                    "An observation-linked decision uses extraction review provenance.",
                )
            source_run = db.get(Extraction, observation.extraction_run_id)
            if source_run.document_version_id != version.id or (run and source_run.id != run.id):
                fail(
                    "OBSERVATION_SOURCE_MISMATCH",
                    "Observation does not belong to this extraction/source.",
                )
            if path.startswith("lines."):
                if observation.field_path != f"lines.*.{path.split('.')[-1]}":
                    fail("OBSERVATION_SOURCE_MISMATCH", "Observation describes a different field.")
                line_ref = path.split(".")[1]
                expected_row = (
                    alignments.get(line_ref)
                    if alignments
                    else db.get(LineIdentity, line_ref).source_row_key
                )
                if expected_row != observation.row_key:
                    fail(
                        "OBSERVATION_SOURCE_MISMATCH", "Observation belongs to another source row."
                    )
            elif observation.field_path != path:
                fail("OBSERVATION_SOURCE_MISMATCH", "Observation describes another field.")
            if decision.decision == "CONFIRMED" and actual != observation.normalised_value_json:
                fail(
                    "VALIDATION_ERROR",
                    "Use CORRECTED with a reason when the proposed value changes.",
                    path,
                    422,
                )
        elif decision.provenance != "HUMAN_TRANSCRIPTION":
            fail("OBSERVATION_SOURCE_MISMATCH", "No observation: use explicit human transcription.")
        source = (
            locator(db, version.id, decision.source_locator)
            if decision.source_locator
            else (observation.source_locator_json if observation else None)
        )
        if observation and source != observation.source_locator_json:
            fail(
                "OBSERVATION_SOURCE_MISMATCH",
                "Keep the original observation locator for corrections.",
            )
        if decision.decision in {"UNRESOLVED", "NOT_APPLICABLE"} and actual is not None:
            fail(
                "VALIDATION_ERROR",
                "Unresolved/non-applicable effective values must be null.",
                path,
                422,
            )
        data = decision.model_dump(mode="json")
        data["document_line_ref"] = line_ref
        data["source_locator"] = source
        decision_values.append(data)
        db.add(
            FieldDecision(
                fact_revision_id=revision.id,
                field_path=path,
                document_line_ref=line_ref,
                observation_id=observation.id if observation else None,
                decision=decision.decision,
                effective_value_json=actual,
                provenance=decision.provenance,
                reason=decision.reason,
                source_locator_json=source,
            )
        )
    revision.content_hash = digest(
        {"canonical_document": canonical, "field_decisions": decision_values}
    )
    db.add(revision)
    for index, line in enumerate(canonical["lines"]):
        db.add(
            ReviewedLine(
                fact_revision_id=revision.id,
                document_line_ref=line["document_line_ref"],
                line_order=index + 1,
                line_json=line,
            )
        )
    if (
        old
        and old_lines
        and not old_lines <= {line["document_line_ref"] for line in canonical["lines"]}
    ):
        doc.current_mapping_revision_id = None
    doc.latest_draft_fact_revision_id = revision.id
    touch(doc)
    record(
        db,
        ctx,
        "DOCUMENT_REVIEW_DRAFT_SAVED",
        doc,
        version,
        {"fact_revision_id": revision.id, "content_hash": revision.content_hash},
    )
    return fact_view(db, ctx, revision)


def issue_line(db, ctx, ident, payload):
    version, doc, _ = access.version(db, ctx, ident, "document.review", True)
    if version.id != doc.current_version_id:
        fail("SOURCE_VERSION_CHANGED", "New lines belong to the current source only.")
    row = LineIdentity(
        id=uid(),
        document_version_id=version.id,
        issued_by_user_id=ctx.user.id,
        reason=payload.reason[:200],
    )
    db.add(row)
    record(db, ctx, "DOCUMENT_MANUAL_LINE_IDENTITY_ISSUED", doc, version, {"line_ref": row.id})
    return result(row, doc)


def fact_view(db, ctx, revision):
    _, doc, _ = access.version(db, ctx, revision.document_version_id)
    if not access.full_capture(db, ctx, doc) and revision.id != doc.effective_fact_revision_id:
        fail("NOT_FOUND", "Reviewed snapshot not found.", status=404)
    return {
        **result(revision, doc),
        "etag": f'"{doc.row_version}"',
        "field_decisions": [
            result(d, doc)
            for d in db.scalars(
                select(FieldDecision).where(FieldDecision.fact_revision_id == revision.id)
            )
        ],
        "document_id": doc.id,
    }


def submit(db, ctx, ident, payload):
    revision = exists(db, FactRevision, ident)
    version, doc, _ = access.version(
        db, ctx, revision.document_version_id, "document.review.submit", True
    )
    match(ctx, doc)
    if version.id != doc.current_version_id:
        fail("SOURCE_VERSION_CHANGED", "Source changed before submission.")
    if (
        doc.latest_draft_fact_revision_id != revision.id
        or revision.content_hash != payload.content_hash
    ):
        fail("REVIEW_HEAD_CHANGED", "Submit the exact current fact revision and content hash.")
    decisions = list(
        db.scalars(select(FieldDecision).where(FieldDecision.fact_revision_id == revision.id))
    )
    if not set(flatten(revision.canonical_document_json)) <= {d.field_path for d in decisions}:
        fail(
            "OBSERVATION_SOURCE_MISMATCH", "Review every proposed non-null field before submitting."
        )
    unresolved = any(d.decision == "UNRESOLVED" for d in decisions) or not (
        revision.canonical_document_json["header"].get("document_number")
        and revision.canonical_document_json["header"].get("issue_date")
    )
    state = "REVIEWED_WITH_UNRESOLVED_FIELDS" if unresolved else "REVIEWED"
    row = ReviewDecision(
        fact_revision_id=revision.id,
        decision="SUBMIT_REVIEW",
        review_state=state,
        content_hash=revision.content_hash,
        note=payload.review_note,
        actor_user_id=ctx.user.id,
        actor_organization_id=ctx.org_id,
    )
    db.add(row)
    doc.effective_fact_revision_id = revision.id
    touch(doc)
    record(
        db,
        ctx,
        "DOCUMENT_REVIEW_SUBMITTED",
        doc,
        version,
        {
            "fact_revision_id": revision.id,
            "review_state": state,
            "dispatch_readiness": "NOT_ASSESSED",
        },
    )
    return {
        **result(row, doc),
        "etag": f'"{doc.row_version}"',
        "dispatch_readiness": "NOT_ASSESSED",
    }
