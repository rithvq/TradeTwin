"""Explain each exact binding without deriving a second release decision."""

from sqlalchemy import select

from app.operations.models import Assignment, Vehicle
from app.trades.errors import TradeError
from app.trades.terms import digest

from . import context, dispatch
from .clock import aware
from .models import Authorization, Manifest, Packet, PacketAck, ReleaseReview


def item(label, row, matches=True, reasons=None):
    return {
        "label": label,
        "status": "MISSING" if row is None else "CURRENT" if matches else "CHANGED",
        "reference": row.id if row else None,
        "reason_codes": reasons
        or ([label.upper().replace(" ", "_") + "_CHANGED"] if row and not matches else []),
    }


def read(db, evaluation, trade, cn, authorization, historical, freshness):
    if not evaluation:
        return {
            "items": [
                item(label, None)
                for label in (
                    "Evaluation",
                    "Reviewer approval",
                    "Dispatch packet",
                    "Driver acknowledgment",
                    "Assignment",
                    "Loading manifest",
                )
            ],
            "manifest_path": None,
            "notice": "No evaluation has been captured for this action.",
        }
    token = db.get(Authorization, authorization["id"]) if authorization else None
    head = context.heads(db, cn)
    head_id = getattr(
        head,
        "current_pickup_evaluation_id"
        if evaluation.action == "PICKUP_CONFIRMED"
        else "current_departure_evaluation_id",
        None,
    )
    review = (
        db.get(ReleaseReview, token.approval_id)
        if token
        else db.scalar(
            select(ReleaseReview)
            .where(ReleaseReview.evaluation_id == evaluation.id)
            .order_by(ReleaseReview.created_at.desc(), ReleaseReview.id.desc())
            .limit(1)
        )
    )
    packet = (
        db.get(Packet, token.packet_id)
        if token
        else db.scalar(
            select(Packet)
            .where(Packet.evaluation_id == evaluation.id)
            .order_by(Packet.created_at.desc(), Packet.id.desc())
            .limit(1)
        )
    )
    ack = (
        db.get(PacketAck, token.acknowledgment_id)
        if token
        else (
            db.scalar(
                select(PacketAck)
                .where(PacketAck.packet_id == packet.id)
                .order_by(PacketAck.created_at.desc(), PacketAck.id.desc())
                .limit(1)
            )
            if packet
            else None
        )
    )
    assignment_id = (
        token.assignment_id
        if token
        else (evaluation.snapshot_json.get("assignment") or {}).get("id")
    )
    assignment = db.get(Assignment, assignment_id) if assignment_id else None
    manifest = (
        db.get(Manifest, evaluation.loading_manifest_revision_id)
        if evaluation.loading_manifest_revision_id
        else None
    )
    evaluation_matches = historical or (
        freshness == "CURRENT"
        and head_id == evaluation.id
        and (not token or token.evaluation_id == evaluation.id)
    )
    reviewed = bool(
        review
        and review.evaluation_id == evaluation.id
        and review.evaluation_hash == evaluation.evaluation_hash
        and review.decision == "APPROVE_RELEASE"
    )
    if reviewed and not historical:
        try:
            dispatch.approval(db, evaluation, review.id)
        except TradeError:
            reviewed = False
    packed = bool(
        packet
        and packet.evaluation_id == evaluation.id
        and review
        and packet.approval_id == review.id
        and packet.loading_manifest_revision_id == evaluation.loading_manifest_revision_id
    )
    if packed and not historical:
        try:
            dispatch.packet_current(db, packet, trade, cn)
        except TradeError:
            packed = False
    acked = bool(
        ack
        and packet
        and assignment
        and ack.packet_id == packet.id
        and ack.packet_hash == packet.packet_hash
        and ack.assignment_id == assignment.id
        and ack.created_by_user_id == assignment.driver_user_id
    )
    original = evaluation.snapshot_json.get("assignment") or {}
    vehicle = db.get(Vehicle, assignment.vehicle_id) if assignment else None
    live_vehicle = (
        {
            "id": vehicle.id,
            "active": vehicle.active,
            "registration_number": vehicle.registration_number,
            "vehicle": vehicle.vehicle_json,
        }
        if vehicle
        else None
    )
    assigned = bool(
        assignment
        and (
            historical
            or (
                cn.active_assignment_id == assignment.id
                and assignment.status == "ACCEPTED"
                and all(
                    getattr(assignment, key) == original.get(key)
                    for key in (
                        "vehicle_id",
                        "driver_user_id",
                        "vehicle_snapshot",
                        "driver_snapshot",
                    )
                )
                and aware(assignment.booking_start_at).isoformat()
                == original.get("booking_start_at")
                and aware(assignment.booking_end_at).isoformat() == original.get("booking_end_at")
                and digest(live_vehicle) == digest(evaluation.snapshot_json.get("current_vehicle"))
            )
        )
    )
    manifested = bool(
        manifest
        and (not token or token.loading_manifest_revision_id == manifest.id)
        and (historical or (head and head.current_loading_manifest_revision_id == manifest.id))
    )
    return {
        "notice": (
            "Authorization belongs to an earlier evaluation. Its status follows the existing gate. "
            "The newer evaluation requires its own approval, packet, driver acknowledgment "
            "and authorization."
        )
        if token and token.evaluation_id != evaluation.id
        else (
            "These identifiers describe the exact release chain; calculation reuse grants "
            "no release permission."
        ),
        "items": [
            item("Evaluation", evaluation, evaluation_matches),
            item("Reviewer approval", review, reviewed),
            item("Dispatch packet", packet, packed),
            item("Driver acknowledgment", ack, acked and packed and assigned),
            item("Assignment", assignment, assigned),
            item("Loading manifest", manifest, manifested),
        ],
        "manifest_path": f"/compliance-evaluations/{evaluation.id}/evidence-manifest",
    }
