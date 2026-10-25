"""Explicit provider lineage. Unknown derived fields are never assumed independent."""

from copy import deepcopy

from sqlalchemy import select

from app.document_desk.models import Document
from app.trades.terms import digest

from . import scope_epochs

MOVEMENT = ("TAX_INVOICE", "BILL_OF_SUPPLY", "DELIVERY_CHALLAN")
EWB = ("EWAY_BILL_COPY",)
TRANSPORT = (
    "VEHICLE_RC",
    "VEHICLE_INSURANCE",
    "FITNESS_CERTIFICATE",
    "PUC_CERTIFICATE",
    "GOODS_PERMIT",
    "PERMIT_AUTHORISATION",
    "DRIVER_LICENCE",
    "CARGO_INSURANCE",
)
DOCUMENT_TYPES = (*MOVEMENT, *EWB, *TRANSPORT)
PROVIDERS = {
    "movement_invoice": ("invoice",),
    "invoice_formalities": ("invoice", "inherited"),
    "whole_invoice_coverage": ("invoice", "binding"),
    "loading_manifest": ("loading",),
    "invoice_reservation": ("invoice", "reservation"),
    "carried_documents": ("binding",),
    "einvoice_signature": ("invoice", "verification"),
    "hsn_digits": ("invoice", "turnover"),
    "supplier_gst_active": ("invoice", "verification", "inherited"),
    "recipient_gst_active": ("invoice", "verification", "inherited"),
    "authority_assurance": ("invoice", "verification", "inherited"),
    "einvoice_present": ("invoice",),
    "irn_live": ("invoice", "verification"),
    "einvoice_proof": ("invoice", "verification"),
    "irp_reporting_window": ("invoice",),
    "ewb_present": ("ewb",),
    "ewb_identity": ("invoice", "ewb", "verification", "assignment", "inherited"),
    "ewb_validity": ("invoice", "ewb", "verification", "assignment", "inherited"),
    "ewb_arrival_window": ("ewb", "facts"),
    "ewb_portal_controls": ("invoice", "ewb"),
    "transport_assurance": ("transport", "assignment", "facts", "inherited"),
    "scope_supported": ("scope",),
}
DIAGNOSTICS = {
    "SUPPORTED_SCOPE": ("scope",),
    "LOADING_MANIFEST": ("loading",),
    "EWB_IDENTITY": PROVIDERS["ewb_identity"],
}


def capture(db, trade):
    """Include unreviewed query matches; only the binding provider selects evidence."""
    documents = list(
        db.scalars(select(Document).where(Document.trade_id == trade.id).order_by(Document.id))
    )
    kinds = sorted(set(DOCUMENT_TYPES) | {d.document_type for d in documents})
    return {
        "provider_version": "PH4_LINEAGE_V1",
        "epochs": scope_epochs.capture(db, trade.id, kinds),
        "queries": {
            kind: {
                "kind": "EVIDENCE_QUERY",
                "document_type": kind,
                "required_review_state": "SUBMITTED_AND_BOUND",
                "trade_id": trade.id,
                "matching_revisions": [
                    {
                        "document_id": d.id,
                        "current_version_id": d.current_version_id,
                        "reviewed_fact_revision_id": d.effective_fact_revision_id,
                        "canonical_document_id": d.canonical_document_id or d.id,
                        "mapping_revision_id": d.current_mapping_revision_id,
                        "lifecycle_status": d.lifecycle_status,
                    }
                    for d in documents
                    if d.document_type == kind
                ],
            }
            for kind in kinds
        },
    }


def sources(group, snapshot):
    ctx, data = snapshot["context"], snapshot["data"]
    movement_id = (data.get("binding") or {}).get("movement_document", {}).get("document_id")
    if group == "invoice":
        return (
            {
                "documents": [
                    d for d in ctx["documents"] if d["reference"]["document_id"] == movement_id
                ],
                "reference": (data.get("binding") or {}).get("movement_document"),
            },
            MOVEMENT,
            (),
        )
    if group == "ewb":
        return (
            {
                "documents": [
                    d for d in ctx["documents"] if d["reference"]["document_id"] != movement_id
                ],
                "supporting": (data.get("binding") or {}).get("supporting_documents", []),
            },
            EWB,
            (),
        )
    if group == "verification":
        return (
            {
                name: ctx[name]
                for name in ("verification_results", "manual_observations", "trusted_keys")
            },
            (),
            ("VERIFICATION",),
        )
    if group == "transport":
        return (
            {
                "evidence": ctx["transport"],
                "selected": (data.get("binding") or {}).get("transport_evidence_revision_ids", []),
            },
            TRANSPORT,
            ("TRANSPORT",),
        )
    if group == "assignment":
        return (
            {name: ctx.get(name) for name in ("assignment", "current_vehicle")},
            (),
            ("ASSIGNMENT",),
        )
    if group == "inherited":
        return ctx["inherited"], (), ("TERMS",)
    if group == "facts":
        return ctx["fact"], (), ("FACTS",)
    if group == "turnover":
        return ctx["turnover"], (), ("TURNOVER",)
    if group == "loading":
        return (
            {name: ctx.get(name) for name in ("manifest", "assignment", "pickup_events")},
            (),
            ("LOADING", "ASSIGNMENT", "TERMS"),
        )
    if group == "reservation":
        return (
            {
                "reservation_id": (data.get("binding") or {}).get("reservation_id"),
                "current_value": data.get("proof", {}).get("invoice_reservation"),
            },
            (),
            ("RESERVATION",),
        )
    if group == "binding":
        return ctx["binding"], (), ("BINDING",)
    if group == "scope":
        return (
            {
                "context": ctx,
                "data": data,
                "plan_valid": snapshot["plan_valid"],
                "recipient_current": snapshot["recipient_current"],
            },
            DOCUMENT_TYPES,
            tuple(scope_epochs.GROUPS),
        )
    raise ValueError("Unregistered dependency provider")


def witness(group, snapshot):
    value, kinds, groups = sources(group, snapshot)
    lineage = snapshot["lineage"]
    witnesses = [{"kind": "PROVIDER_INPUT", "provider": group, "content_hash": digest(value)}]
    for kind in kinds:
        # Pin the full negative selection query, including canonical identity and mapping heads.
        witnesses.append(deepcopy(lineage["queries"][kind]))
    keys = [scope_epochs.key(snapshot["trade_id"], group) for group in groups]
    keys += [scope_epochs.key(snapshot["trade_id"], "DOC:" + kind) for kind in kinds]
    if group in {"assignment", "transport"}:
        keys.append("global:VEHICLES")
    if group == "verification":
        keys.append("global:VERIFICATION")
    ready = True
    for key in sorted(set(keys)):
        state = lineage["epochs"].get(key)
        if not state:
            ready = False
            witnesses.append({"kind": "MISSING_SCOPE", "scope_key": key})
        else:
            ready = ready and not state["initialised_now"]
            witnesses.append(
                {
                    "kind": "SCOPE_EPOCH",
                    "scope_key": key,
                    "generation_id": state["generation_id"],
                    "epoch": state["epoch"],
                }
            )
    return witnesses, ready
