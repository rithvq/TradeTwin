from sqlalchemy import select

from app.operations.access import consignment, exists, fail, has, lock_trade
from app.operations.models import Assignment, Attachment, Consignment
from app.trades.access import participant_role, require
from app.trades.errors import TradeError
from app.trades.models import Participant, Trade

from .models import AccessGrant, Asset, Document, SubjectLink, Version

FINANCIAL = {"TAX_INVOICE", "BILL_OF_SUPPLY", "PURCHASE_ORDER", "SIGNED_EINVOICE_JSON"}
INVOICE_PRESENTATIONS = {"TAX_INVOICE", "SIGNED_EINVOICE_JSON"}
OPERATIONAL = {"LR_GR", "POD", "PACKING_LIST", "EWAY_BILL_COPY", "DELIVERY_CHALLAN"}
TRANSPORT = {
    "VEHICLE_RC",
    "VEHICLE_INSURANCE",
    "FITNESS_CERTIFICATE",
    "PUC_CERTIFICATE",
    "GOODS_PERMIT",
    "PERMIT_AUTHORISATION",
    "DRIVER_LICENCE",
    "CARGO_INSURANCE",
}
OPERATIONAL_PATHS = {
    "header.document_number",
    "header.issue_date",
    "packing_transport.package_count",
    "packing_transport.gross_weight_kg",
    "packing_transport.net_weight_kg",
    "packing_transport.lr_gr_number",
    "packing_transport.vehicle_registration_number",
    "eway_bill.eway_bill_number",
    "eway_bill.valid_from_at",
    "eway_bill.valid_until_at",
}


def active_assignment(db, ctx, assignment):
    if (
        not assignment
        or assignment.carrier_organization_id != ctx.org_id
        or assignment.status != "ACCEPTED"
    ):
        return False
    cn = db.get(Consignment, assignment.consignment_id)
    if not cn or cn.active_assignment_id != assignment.id:
        return False
    try:
        consignment(db, ctx, cn.id)
        return True
    except TradeError:
        return False


def document(db, ctx, ident, permission="document.read", lock=False, projection=False):
    row = exists(db, Document, ident)
    from app.compliance.models import PrivateSource

    protected = db.scalar(select(PrivateSource).where(PrivateSource.document_id == row.id))
    if protected and protected.seller_organisation_id != ctx.org_id:
        fail("NOT_FOUND", "Document not found.", status=404)
    if protected:
        require(db, ctx.user, ctx.org_id, "turnover.read")
    if row.document_type == "DRIVER_LICENCE" and row.owner_organization_id != ctx.org_id:
        fail("NOT_FOUND", "Document not found.", status=404)
    trade = lock_trade(db, row.trade_id) if lock else exists(db, Trade, row.trade_id)
    if lock:
        db.refresh(row)
    if lock and row.lifecycle_status == "ARCHIVED":
        fail("DOCUMENT_ARCHIVED", "Archived evidence is read-only; register a new document.")
    side = participant_role(db, trade.id, ctx.org_id)
    sensitive_assets = bool(
        db.scalar(
            select(Asset.id)
            .join(Attachment)
            .join(Version)
            .where(
                Version.document_id == row.id,
                Attachment.purpose.in_(["DOCUMENT_FINANCIAL", "PAYMENT"]),
            )
        )
    )
    owner = row.owner_organization_id == ctx.org_id
    grants = list(
        db.scalars(
            select(AccessGrant).where(
                AccessGrant.document_version_id == row.current_version_id,
                AccessGrant.grantee_organization_id == ctx.org_id,
                AccessGrant.revoked_at.is_(None),
            )
        )
    )
    shared = side and (
        row.visibility == "TRADE_PARTIES"
        or any(g.access_type in {"READ_REVIEWED", "DOWNLOAD_ORIGINAL"} for g in grants)
    )
    if not side:
        if row.document_type in TRANSPORT and not (
            has(db, ctx, "transport.evidence.prepare", trade.id)
            or has(db, ctx, "transport.evidence.review", trade.id)
        ):
            fail("NOT_FOUND", "Document not found.", status=404)
        if row.document_type in FINANCIAL | {"PAYMENT_EVIDENCE", "OTHER"} or sensitive_assets:
            fail("NOT_FOUND", "Document not found.", status=404)
        own_links = list(
            db.scalars(
                select(SubjectLink).where(
                    SubjectLink.document_version_id == row.current_version_id,
                    SubjectLink.subject_type == "CONSIGNMENT",
                    SubjectLink.revoked_at.is_(None),
                )
            )
        )
        valid = [
            g
            for g in grants
            if g.access_type == "OPERATIONAL_PROJECTION"
            and active_assignment(db, ctx, db.get(Assignment, g.assignment_id))
        ]
        historical_owner = (
            owner
            and row.document_type in {"LR_GR", "POD"}
            and any(
                db.scalar(
                    select(Assignment.id).where(
                        Assignment.consignment_id == link.subject_id,
                        Assignment.carrier_organization_id == ctx.org_id,
                    )
                )
                for link in own_links
            )
        )
        current_transport_owner = (
            owner
            and row.document_type in TRANSPORT
            and any(
                active_assignment(db, ctx, assignment)
                for link in own_links
                for assignment in db.scalars(
                    select(Assignment).where(Assignment.consignment_id == link.subject_id)
                )
            )
        )
        if not historical_owner and not current_transport_owner and not valid:
            fail("NOT_FOUND", "Document not found.", status=404)
        if not owner and not projection:
            fail("FORBIDDEN", "Only the approved operational projection is available.", status=403)
        if permission not in {"document.read", "document.original.download"}:
            if not owner or row.document_type not in {"LR_GR", "POD"} | TRANSPORT:
                fail("FORBIDDEN", "Operational document authority is required.", status=403)
            for link in own_links:
                consignment(db, ctx, link.subject_id)
        require(db, ctx.user, ctx.org_id, permission, trade.id)
    else:
        if not owner and not shared:
            fail("NOT_FOUND", "Document not found.", status=404)
        require(db, ctx.user, ctx.org_id, permission, trade.id, side)
        if permission != "document.read":
            require(db, ctx.user, ctx.org_id, "document.read", trade.id, side)
        if (
            not owner
            and row.visibility != "TRADE_PARTIES"
            and permission not in {"document.read", "document.check"}
        ):
            if not any(g.access_type == "DOWNLOAD_ORIGINAL" for g in grants):
                fail("FORBIDDEN", "This grant shares submitted reviewed values only.", status=403)
        if row.document_type in FINANCIAL or sensitive_assets:
            require(db, ctx.user, ctx.org_id, "document.financial.read", trade.id, side)
        if row.document_type == "PAYMENT_EVIDENCE":
            require(db, ctx.user, ctx.org_id, "document.payment_evidence.read", trade.id, side)
        if (
            permission == "document.original.download"
            and not owner
            and row.visibility != "TRADE_PARTIES"
        ):
            if not any(g.access_type == "DOWNLOAD_ORIGINAL" for g in grants):
                fail("FORBIDDEN", "Original download was not shared.", status=403)
    return row, trade


def version(db, ctx, ident, permission="document.read", lock=False):
    row = exists(db, Version, ident)
    doc, trade = document(db, ctx, row.document_id, permission, lock)
    if (
        row.id != doc.current_version_id
        and doc.owner_organization_id != ctx.org_id
        and doc.visibility != "TRADE_PARTIES"
    ):
        if not db.scalar(
            select(AccessGrant.id).where(
                AccessGrant.document_version_id == row.id,
                AccessGrant.grantee_organization_id == ctx.org_id,
                AccessGrant.access_type == "DOWNLOAD_ORIGINAL",
                AccessGrant.revoked_at.is_(None),
            )
        ):
            fail("NOT_FOUND", "Source version not found.", status=404)
    if not full_capture(db, ctx, doc) and row.id != doc.current_version_id:
        fail("NOT_FOUND", "Source version not found.", status=404)
    return row, doc, trade


def allowed(db, ctx, row):
    codes = [
        "document.register",
        "document.read",
        "document.process",
        "document.review",
        "document.review.submit",
        "document.map",
        "document.check",
        "document.verify.request",
        "document.share",
        "document.archive",
        "document.version.add",
        "document.original.download",
        "document.manual_attestation.record",
    ]
    result = []
    for code in codes:
        if row.canonical_document_id and code == "document.map":
            continue
        if row.lifecycle_status == "ARCHIVED" and code not in {
            "document.read",
            "document.original.download",
            "document.share",
        }:
            continue
        try:
            document(db, ctx, row.id, code)
            result.append(code)
        except TradeError:
            continue
    return result


def registration_access(db, ctx, trade_id, document_type, consignment_id=None):
    trade = lock_trade(db, str(trade_id))
    side = participant_role(db, trade.id, ctx.org_id)
    if side:
        require(db, ctx.user, ctx.org_id, "document.register", trade.id, side)
        require(db, ctx.user, ctx.org_id, "document.read", trade.id, side)
        if document_type in FINANCIAL:
            require(db, ctx.user, ctx.org_id, "document.financial.read", trade.id, side)
        if document_type == "PAYMENT_EVIDENCE":
            require(db, ctx.user, ctx.org_id, "document.payment_evidence.read", trade.id, side)
    elif (
        document_type
        in {
            "LR_GR",
            "POD",
            "VEHICLE_RC",
            "VEHICLE_INSURANCE",
            "FITNESS_CERTIFICATE",
            "PUC_CERTIFICATE",
            "GOODS_PERMIT",
            "PERMIT_AUTHORISATION",
            "DRIVER_LICENCE",
            "CARGO_INSURANCE",
        }
        and consignment_id
    ):
        _, cn, _ = consignment(db, ctx, consignment_id, "attachment.upload")
        if cn.trade_id != trade.id:
            fail("NOT_FOUND", "Trade not found.", status=404)
        require(db, ctx.user, ctx.org_id, "document.register", trade.id)
    else:
        fail("NOT_FOUND", "Trade not found.", status=404)
    return trade


def recipient(db, doc, organization_id):
    return db.scalar(
        select(Participant).where(
            Participant.trade_id == doc.trade_id,
            Participant.organization_id == str(organization_id),
        )
    )


def protected_attachment(db, ctx, attachment):
    # Once registered, bytes inherit every linked document's sensitivity, not just upload purpose.
    assets = list(db.scalars(select(Asset).where(Asset.attachment_id == attachment.id)))
    for asset in assets:
        v = db.get(Version, asset.document_version_id)
        version(db, ctx, v.id, "document.original.download")
    if attachment.purpose == "DOCUMENT_FINANCIAL":
        require(db, ctx.user, ctx.org_id, "document.financial.read", attachment.trade_id)
    if attachment.purpose in {"DOCUMENT_FINANCIAL", "DOCUMENT_OPERATIONAL"} and not assets:
        if attachment.uploaded_by_organization_id != ctx.org_id:
            fail("NOT_FOUND", "Attachment not found.", status=404)
        require(db, ctx.user, ctx.org_id, "document.original.download", attachment.trade_id)


def can_read(db, ctx, row):
    try:
        document(db, ctx, row.id)
        return True
    except TradeError:
        return False


def full_capture(db, ctx, doc):
    if doc.owner_organization_id == ctx.org_id or doc.visibility == "TRADE_PARTIES":
        return True
    return bool(
        db.scalar(
            select(AccessGrant.id).where(
                AccessGrant.document_version_id == doc.current_version_id,
                AccessGrant.grantee_organization_id == ctx.org_id,
                AccessGrant.access_type == "DOWNLOAD_ORIGINAL",
                AccessGrant.revoked_at.is_(None),
            )
        )
    )


def capture(db, ctx, doc):
    if not full_capture(db, ctx, doc):
        fail(
            "FORBIDDEN",
            "Only submitted reviewed values were shared; source capture is private.",
            status=403,
        )


def can_register(db, ctx, trade):
    side = participant_role(db, trade.id, ctx.org_id)
    return bool(side and has(db, ctx, "document.register", trade.id, side))
