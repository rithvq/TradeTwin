"""Exact effective dependencies, excluding approval/packet/ACK/token workflow records."""

from sqlalchemy import or_, select

from app.document_desk.models import (
    Asset,
    Document,
    FactRevision,
    MappingRevision,
    Version,
)
from app.operations.access import consignment, exists, fail
from app.operations.models import Assignment, Attachment, ConsignmentItem, Event, Vehicle
from app.trades.access import aware
from app.trades.models import Participant, Revision
from app.trades.terms import digest

from .models import (
    Binding,
    Fact,
    Heads,
    Hold,
    HoldEvent,
    Manifest,
    RecipientConfirmation,
    TradeContext,
    TransportEvidence,
    TransportReview,
    Turnover,
    TurnoverReview,
)


def access(db, ctx, ident, permission="compliance.read", seller=False, lock=False):
    trade, cn, side = consignment(db, ctx, ident, permission, "SELLER" if seller else None, lock)
    return trade, cn, side


def version(db, trade_id):
    value = db.scalar(select(TradeContext.context_version).where(TradeContext.trade_id == trade_id))
    return value if value is not None else 0


def heads(db, cn, create=False):
    row = db.get(Heads, cn.id)
    if row is None and create:
        row = Heads(consignment_id=cn.id)
        db.add(row)
        db.flush()
    return row


def inherited(db, trade, cn):
    revision = (
        exists(db, Revision, trade.accepted_revision_id) if trade.accepted_revision_id else None
    )
    if revision is None:
        fail("COMPLIANCE_NOT_READY", "Confirm the trade before preparing compliance facts.")
    facts = revision.facts_json
    parties = {
        p.participant_role: p.organization_id
        for p in db.scalars(select(Participant).where(Participant.trade_id == trade.id))
    }
    bill_from, bill_to = facts.get("bill_from", {}), facts.get("bill_to", {})
    assignment = db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    cargo = list(db.scalars(select(ConsignmentItem).where(ConsignmentItem.consignment_id == cn.id)))
    return {
        "trade_id": trade.id,
        "consignment_id": cn.id,
        "accepted_trade_revision_id": revision.id,
        "accepted_terms_hash": revision.terms_hash,
        "assignment_id": assignment.id if assignment else None,
        "execution_mode": trade.execution_mode,
        "movement_purpose": facts.get("movement_purpose"),
        "transport_mode": facts.get("delivery_requirements", {}).get("mode"),
        "transaction_layout": facts.get("transaction_layout"),
        "currency": facts.get("currency"),
        "origin_state_code": cn.pickup_address_snapshot.get("state_code"),
        "destination_state_code": cn.delivery_address_snapshot.get("state_code"),
        "seller_organisation_id": parties.get("SELLER"),
        "buyer_organisation_id": parties.get("BUYER"),
        "seller_registration_id": facts.get("seller_registration_id"),
        "buyer_registration_id": facts.get("buyer_registration_id"),
        "seller_gstin": bill_from.get("gstin"),
        "scope": facts.get("scope"),
        "seller_registration_state_code": bill_from["gstin"][:2]
        if bill_from.get("gstin")
        else None,
        "buyer_registration_state_code": bill_to["gstin"][:2] if bill_to.get("gstin") else None,
        "buyer_gstin": bill_to.get("gstin"),
        "seller_registration_position": bill_from.get("registration_position"),
        "buyer_registration_position": bill_to.get("registration_position"),
        "seller_tax_scheme": bill_from.get("declared_taxpayer_scheme"),
        "seller_establishment_kind": bill_from.get("declared_establishment_kind"),
        "buyer_establishment_kind": bill_to.get("declared_establishment_kind"),
        "hazardous_declared": None
        if any(i.cargo_declarations_snapshot.get("hazardous_declared") is None for i in cargo)
        else any(i.cargo_declarations_snapshot.get("hazardous_declared") for i in cargo),
        "temperature_controlled": any(
            i.cargo_declarations_snapshot.get("temperature_controlled") for i in cargo
        ),
        "insurance_required": facts.get("commercial_terms", {}).get("insurance_required"),
    }


def dependency_snapshot(db, trade, cn, registry_manifest):
    head = heads(db, cn)
    binding = (
        db.get(Binding, head.current_binding_revision_id)
        if head and head.current_binding_revision_id
        else None
    )
    fact = (
        db.get(Fact, head.current_fact_revision_id)
        if head and head.current_fact_revision_id
        else None
    )
    manifest = (
        db.get(Manifest, head.current_loading_manifest_revision_id)
        if head and head.current_loading_manifest_revision_id
        else None
    )
    assignment = db.get(Assignment, cn.active_assignment_id) if cn.active_assignment_id else None
    vehicle = db.get(Vehicle, assignment.vehicle_id) if assignment else None
    value = {
        "schema_version": "PH4_DEPENDENCIES_V1",
        "recipient_confirmation": recipient_state(db, cn),
        "inherited": inherited(db, trade, cn),
        "context_version": version(db, trade.id),
        "registry_manifest": registry_manifest,
        "consignment": {
            "planning_status": cn.planning_status,
            "movement_status": cn.movement_status,
            "revision_alignment": cn.revision_alignment,
            "plan": cn.plan_json,
            "pickup": cn.pickup_address_snapshot,
            "delivery": cn.delivery_address_snapshot,
        },
        "assignment": {
            "id": assignment.id,
            "status": assignment.status,
            "vehicle_id": assignment.vehicle_id,
            "driver_user_id": assignment.driver_user_id,
            "vehicle_snapshot": assignment.vehicle_snapshot,
            "driver_snapshot": assignment.driver_snapshot,
            "booking_start_at": aware(assignment.booking_start_at).isoformat(),
            "booking_end_at": aware(assignment.booking_end_at).isoformat(),
        }
        if assignment
        else None,
        "current_vehicle": {
            "id": vehicle.id,
            "active": vehicle.active,
            "registration_number": vehicle.registration_number,
            "vehicle": vehicle.vehicle_json,
        }
        if vehicle
        else None,
        "fact": {"id": fact.id, "hash": fact.content_hash, "facts": fact.facts_json}
        if fact
        else None,
        "binding": {
            "id": binding.id,
            "hash": binding.content_hash,
            "bindings": binding.binding_json,
        }
        if binding
        else None,
        "manifest": {
            "id": manifest.id,
            "hash": manifest.content_hash,
            "manifest": manifest.manifest_json,
        }
        if manifest
        else None,
        "documents": [],
        "verification_results": [],
        "manual_observations": [],
        "transport": [],
        "turnover": None,
        "holds": [],
        "pickup_events": [],
        "trusted_keys": [],
    }
    if binding:
        refs = [
            binding.binding_json["movement_document"],
            *binding.binding_json.get("supporting_documents", []),
        ]
        for ref in refs:
            doc, source, reviewed = (
                db.get(Document, ref["document_id"]),
                db.get(Version, ref["document_version_id"]),
                db.get(FactRevision, ref["reviewed_fact_revision_id"]),
            )
            mapping = (
                db.get(MappingRevision, ref.get("mapping_revision_id"))
                if ref.get("mapping_revision_id")
                else None
            )
            value["documents"].append(
                {
                    "reference": ref,
                    "current_version_id": doc.current_version_id,
                    "effective_fact_revision_id": doc.effective_fact_revision_id,
                    "mapping_head": doc.current_mapping_revision_id,
                    "lifecycle_status": doc.lifecycle_status,
                    "canonical_document_id": doc.canonical_document_id or doc.id,
                    "source_hash": source.source_manifest_hash,
                    "fact_hash": reviewed.content_hash,
                    "mapping_hash": mapping.content_hash if mapping else None,
                    "assets": [
                        {
                            "attachment_id": a.attachment_id,
                            "hash": a.asset_sha256,
                            "current_hash": db.get(Attachment, a.attachment_id).sha256,
                            "security_state": db.get(Attachment, a.attachment_id).security_state,
                        }
                        for a in db.scalars(
                            select(Asset)
                            .where(Asset.document_version_id == source.id)
                            .order_by(Asset.id)
                        )
                    ],
                }
            )
        from .dependencies import manual_state, verification_state

        value["verification_results"], value["trusted_keys"] = verification_state(db, binding)
        value["manual_observations"] = manual_state(db, binding)
        for ident in binding.binding_json.get("transport_evidence_revision_ids", []):
            evidence = db.get(TransportEvidence, ident)
            reviews = list(
                db.scalars(
                    select(TransportReview)
                    .where(TransportReview.evidence_revision_id == ident)
                    .order_by(TransportReview.created_at, TransportReview.id)
                )
            )
            value["transport"].append(
                {
                    "id": ident,
                    "hash": evidence.content_hash,
                    "review_ids": [r.id for r in reviews],
                    "source": source_state(db, evidence.document_version_id)
                    if evidence.document_version_id
                    else None,
                }
            )
        if binding.turnover_declaration_id:
            turnover = db.get(Turnover, binding.turnover_declaration_id)
            reviews = list(
                db.scalars(
                    select(TurnoverReview)
                    .where(TurnoverReview.declaration_id == turnover.id)
                    .order_by(TurnoverReview.created_at, TurnoverReview.id)
                )
            )
            value["turnover"] = {
                "id": turnover.id,
                "hash": turnover.content_hash,
                "review_ids": [r.id for r in reviews],
                "source_basis": [source_state(db, i) for i in turnover.source_document_version_ids],
            }
    value["holds"] = [
        {"id": h.id, "active": h.active, "version": h.row_version}
        for h in db.scalars(
            select(Hold)
            .where(
                Hold.trade_id == trade.id,
                or_(Hold.consignment_id == cn.id, Hold.consignment_id.is_(None)),
            )
            .order_by(Hold.id)
        )
    ]
    value["pickup_events"] = [
        {"id": e.id, "hash": e.request_hash, "payload": e.payload_json}
        for e in db.scalars(
            select(Event).where(
                Event.consignment_id == cn.id, Event.event_type == "PICKUP_CONFIRMED"
            )
        )
    ]
    return value, digest(value)


def recipient_state(db, cn):
    row = db.scalar(
        select(RecipientConfirmation)
        .where(RecipientConfirmation.consignment_id == cn.id)
        .order_by(RecipientConfirmation.created_at.desc(), RecipientConfirmation.id.desc())
    )
    return (
        {
            "id": row.id,
            "content_hash": row.content_hash,
            "accepted_trade_revision_id": row.accepted_trade_revision_id,
            "confirmation": row.confirmation_json,
        }
        if row
        else None
    )


def source_state(db, version_id):
    source = db.get(Version, version_id)
    doc = db.get(Document, source.document_id) if source else None
    if not source or not doc:
        return {"version_id": version_id, "missing": True}
    return {
        "version_id": source.id,
        "document_id": doc.id,
        "current_version_id": doc.current_version_id,
        "current_fact_revision_id": doc.effective_fact_revision_id,
        "lifecycle_status": doc.lifecycle_status,
        "source_manifest_hash": source.source_manifest_hash,
        "assets": [
            {
                "id": a.attachment_id,
                "expected_hash": a.asset_sha256,
                "current_hash": db.get(Attachment, a.attachment_id).sha256,
                "security_state": db.get(Attachment, a.attachment_id).security_state,
            }
            for a in db.scalars(
                select(Asset).where(Asset.document_version_id == source.id).order_by(Asset.id)
            )
        ],
    }


def public_context(db, ctx, ident):
    from .ledger import view

    trade, cn, side = access(db, ctx, ident)
    data = inherited(db, trade, cn)
    if side != "SELLER":
        data = {
            key: val
            for key, val in data.items()
            if key not in {"seller_gstin", "seller_registration_id", "seller_organisation_id"}
        }
    from app.trades.access import grants, membership

    from .schemas_facts import Facts

    head = heads(db, cn)
    fact = (
        db.get(Fact, head.current_fact_revision_id)
        if head and head.current_fact_revision_id
        else None
    )
    effective = dict(fact.facts_json) if fact else {}
    if side != "SELLER":
        for key in ("seller_turnover_declaration_id", "field_provenance"):
            effective.pop(key, None)
    from .governance import resolve
    from .selectors import documents

    packs, _, _ = resolve(db, trade.execution_mode)
    return {
        "schema_version": 1,
        "recipient_confirmation": recipient_state(db, cn),
        "recipient_baseline": {
            "gstin": data.get("buyer_gstin"),
            "destination_state_code": cn.delivery_address_snapshot.get("state_code"),
            "address_line1": cn.delivery_address_snapshot.get("address_line1"),
        },
        "trade_id": trade.id,
        "consignment_id": cn.id,
        "inherited_facts": data,
        "documents": documents(db, ctx, trade.id),
        "private_turnover_sources": documents(db, ctx, trade.id, private_basis=True)
        if side == "SELLER"
        and any(
            g.permission_code == "turnover.read"
            for g in grants(db, membership(db, ctx.user, ctx.org_id), trade.id)
        )
        else [],
        "effective_facts": effective,
        "available_scope_codes": sorted(
            {code for pack in packs for code in pack.policy_json["supported_scope_codes"]}
        ),
        "available_commodity_codes": sorted(
            {code for pack in packs for code in pack.policy_json["supported_commodity_codes"]}
        ),
        "context_version": version(db, trade.id),
        "etag": f'"{version(db, trade.id)}"',
        "heads": {c.name: getattr(head, c.name) for c in head.__table__.columns} if head else {},
        "holds": [
            {
                **view(h),
                "events": [
                    view(e)
                    for e in db.scalars(
                        select(HoldEvent)
                        .where(HoldEvent.hold_id == h.id)
                        .order_by(HoldEvent.created_at.desc(), HoldEvent.id.desc())
                    )
                ],
            }
            for h in db.scalars(
                select(Hold)
                .where(
                    Hold.trade_id == trade.id,
                    or_(Hold.consignment_id == cn.id, Hold.consignment_id.is_(None)),
                )
                .order_by(Hold.id)
            )
        ],
        "editable_fields": list(Facts.model_fields) if side == "SELLER" else [],
        "capabilities": sorted(
            {g.permission_code for g in grants(db, membership(db, ctx.user, ctx.org_id), trade.id)}
        ),
        "historical_movement_notice": "Historical movement; Phase 4 authorisation not recorded"
        if cn.phase4_legacy_movement
        else None,
        "fact_revisions": [
            {
                "id": f.id,
                "content_hash": f.content_hash,
                "facts": f.facts_json,
                "submitted_for_review": f.submitted_for_review,
                "prepared_by_user_id": f.created_by_user_id,
                "effective": head is not None and f.id == head.current_fact_revision_id,
            }
            for f in db.scalars(
                select(Fact)
                .where(Fact.consignment_id == cn.id)
                .order_by(Fact.revision_number.desc())
            )
        ]
        if side == "SELLER"
        else [],
        "loading_manifest": db.get(
            Manifest, head.current_loading_manifest_revision_id
        ).manifest_json
        if head and head.current_loading_manifest_revision_id
        else None,
        "transport_evidence": [
            {
                "id": e.id,
                "evidence_type": e.evidence_type,
                "subject_type": e.subject_type,
                "evidence": e.evidence_json
                if e.owner_organisation_id == ctx.org_id
                else {
                    key: val
                    for key, val in e.evidence_json.items()
                    if key
                    in {
                        "valid_from",
                        "valid_until",
                        "covered_states",
                        "source_mode",
                        "permit_basis",
                        "limitations",
                    }
                },
                "prepared_by_user_id": e.created_by_user_id,
                "can_review": e.owner_organisation_id == ctx.org_id
                and e.created_by_user_id != ctx.user.id,
                "review_outcome": (
                    last.decision
                    if (
                        last := db.scalar(
                            select(TransportReview)
                            .where(TransportReview.evidence_revision_id == e.id)
                            .order_by(TransportReview.created_at.desc(), TransportReview.id.desc())
                        )
                    )
                    else "UNREVIEWED"
                ),
            }
            for e in db.scalars(
                select(TransportEvidence)
                .where(
                    TransportEvidence.consignment_id == cn.id,
                    TransportEvidence.assignment_id == cn.active_assignment_id,
                )
                .order_by(TransportEvidence.id)
            )
        ]
        if side == "SELLER" or side is None
        else [],
    }
