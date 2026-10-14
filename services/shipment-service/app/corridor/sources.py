"""Secured manual-source ingress. Provider credentials and arbitrary URLs are not returned."""

from sqlalchemy import select

from app.compliance.clock import instant
from app.compliance.ledger import record, view
from app.operations.access import exists, fail, match
from app.operations.ledger import touch
from app.operations.models import Attachment, AttachmentLink
from app.trades.access import require

from .models import Connection, SourceItem


def owned(db, ctx, ident, permission="regulation.source.register"):
    require(db, ctx.user, ctx.org_id, permission)
    row = exists(db, Connection, ident)
    if row.owner_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Source connection not found.", status=404)
    return row


def public(row):
    data = view(row)
    data["connection_json"] = {
        k: v for k, v in row.connection_json.items() if k != "vault_secret_reference"
    }
    data["etag"] = f'"{row.row_version}"'
    return data


def create(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.source.register")
    if payload.environment == "PRODUCTION" and payload.source_kind == "SIMULATION":
        fail("MODE_MISMATCH", "Simulation sources cannot be configured as production.", status=422)
    if payload.provider_code in {
        "IMD_NOWCAST",
        "IMD_DISTRICT_WARNING",
    } and payload.approved_https_hosts != ["api.imd.gov.in"]:
        fail(
            "SOURCE_ENDPOINT_NOT_APPROVED",
            "IMD connections require the documented official host.",
            status=422,
        )
    row = Connection(
        owner_organisation_id=ctx.org_id,
        provider_code=payload.provider_code,
        source_kind=payload.source_kind,
        environment=payload.environment,
        connection_json=payload.model_dump(mode="json"),
        created_by=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "CORRIDOR_SOURCE_CONFIGURED", row)
    return public(row)


def status(db, ctx, ident, payload):
    row = owned(db, ctx, ident)
    match(ctx, row)
    if payload.status == "CONFIGURED":
        data = row.connection_json
        if (
            data["retention_policy"] != "PERMITTED_ARCHIVE"
            or not data["source_item_storage_allowed"]
        ):
            fail(
                "RETENTION_UNSUPPORTED",
                "Payload ingress needs permitted archival retention; "
                "metadata-only and timed purge remain disabled.",
            )
        if row.provider_code not in {"MANUAL_OFFICIAL", "CARRIER_OBSERVATION", "SIMULATION"}:
            fail(
                "ADAPTER_NOT_ENABLED",
                "Live ingestion is not enabled until endpoint, licensing "
                "and worker integration are validated.",
            )
    row.status = payload.status
    touch(row)
    record(db, ctx, "CORRIDOR_SOURCE_STATUS_CHANGED", row)
    return public(row)


def manual(db, ctx, ident, payload):
    row = owned(db, ctx, payload.source_connection_id)
    if row.status != "CONFIGURED":
        fail("SOURCE_NOT_CONFIGURED", "Configure approved archival ingress first.")
    if (
        payload.retrieved_at > instant(db)
        or payload.source_issued_at
        and payload.source_issued_at > instant(db)
    ):
        fail("VALIDATION_ERROR", "Source times cannot be in the future.", status=422)
    if row.environment == "PRODUCTION" and not payload.artifact_attachment_id:
        fail(
            "SOURCE_ARTIFACT_REQUIRED",
            "Production source ingress requires a clean dedicated secured artifact.",
        )
    if payload.artifact_attachment_id:
        attachment = exists(db, Attachment, payload.artifact_attachment_id)
        from app.document_desk.models import Asset

        if (
            attachment.uploaded_by_organization_id != ctx.org_id
            or attachment.purpose != "OTHER"
            or db.scalar(select(Asset.id).where(Asset.attachment_id == attachment.id))
            or db.scalar(
                select(AttachmentLink.id).where(AttachmentLink.attachment_id == attachment.id)
            )
        ):
            fail(
                "NOT_FOUND",
                "Use a dedicated source artifact, not confidential business evidence.",
                status=404,
            )
        if attachment.security_state != "CLEAN" or attachment.sha256 != payload.payload_sha256:
            fail(
                "SOURCE_SNAPSHOT_INVALID",
                "The secured artifact must be clean and match its server hash.",
            )
    existing = db.scalar(
        select(SourceItem).where(
            SourceItem.source_connection_id == row.id,
            SourceItem.provider_item_key == payload.provider_item_key,
            SourceItem.content_hash == payload.payload_sha256,
        )
    )
    if existing:
        return view(existing)
    item = SourceItem(
        source_connection_id=row.id,
        provider_item_key=payload.provider_item_key,
        content_hash=payload.payload_sha256,
        artifact_attachment_id=str(payload.artifact_attachment_id)
        if payload.artifact_attachment_id
        else None,
        source_issued_at=payload.source_issued_at,
        retrieved_at=payload.retrieved_at,
        item_json=payload.model_dump(mode="json"),
        created_by_user_id=ctx.user.id,
    )
    db.add(item)
    record(db, ctx, "CORRIDOR_SOURCE_ITEM_RETAINED", item)
    return view(item)
