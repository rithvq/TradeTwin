"""Internal-only simulation constructor. Never exposed through a public mutation."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.trades import agreements, profiles
from app.trades.demo import demo_address, demo_facts, demo_profile
from app.trades.models import Organization, Trade, User, now, uid
from app.trades.schemas import (
    Confirmation,
    MembershipChange,
    OrganizationDraft,
    Publish,
    TradeCreate,
)
from app.trades.transactions import Context

from . import transport
from .schemas import CarrierProfileInput, VehicleInput

ROLES = {
    "seller-operations": ("seller", ["ORG_ADMIN", "SELLER_OPERATOR", "SELLER_OPERATIONS"]),
    "seller-approver": ("seller", ["SELLER_APPROVER"]),
    "buyer-receiver": ("buyer", ["ORG_ADMIN", "BUYER_OPERATOR", "BUYER_RECEIVER"]),
    "buyer-approver": ("buyer", ["BUYER_APPROVER"]),
    "buyer-inspector": ("buyer", ["BUYER_INSPECTOR"]),
    "buyer-finance": ("buyer", ["BUYER_FINANCE"]),
    "seller-finance": ("seller", ["SELLER_FINANCE"]),
    "carrier-dispatcher": ("carrier", ["ORG_ADMIN", "CARRIER_DISPATCHER"]),
    "driver-one": ("carrier", ["DRIVER"]),
    "driver-two": ("carrier", ["DRIVER"]),
    "unrelated": ("unrelated", ["ORG_ADMIN", "CARRIER_DISPATCHER", "SELLER_OPERATIONS"]),
}


def seed_demo(db, subjects=None, namespace="phase2", production=False):
    subjects = subjects or {}
    users = {}
    for name in ROLES:
        subject = subjects.get(name, f"operations-demo:{namespace}:{name}")
        user = db.scalar(select(User).where(User.identity_subject == subject))
        if not user:
            user = User(
                id=str(uuid5(NAMESPACE_URL, subject)),
                identity_subject=subject,
                display_name=name,
                email=f"{name}@example.invalid",
                active=True,
            )
            db.add(user)
            db.flush()
        users[name] = user
    orgs = {}
    owners = {
        "seller": "seller-operations",
        "buyer": "buyer-receiver",
        "carrier": "carrier-dispatcher",
        "unrelated": "unrelated",
    }
    for name, owner in owners.items():
        legal = f"Operational demo {namespace} {name}"
        org = db.scalar(select(Organization).where(Organization.legal_name == legal))
        if not org:
            result = profiles.create_organization(
                db,
                Context(users[owner], None, uid()),
                OrganizationDraft.model_validate(demo_profile(legal, demo_address())),
            )
            org = db.get(Organization, result["organization_id"])
        orgs[name] = org.id
    for name, (org, roles) in ROLES.items():
        profiles.change_membership(
            db,
            Context(users[owners[org]], orgs[org], uid()),
            orgs[org],
            MembershipChange(user_id=users[name].id, capabilities=roles),
        )
    ctx = Context(users["carrier-dispatcher"], orgs["carrier"], uid())
    carrier = db.scalar(
        select(transport.Carrier).where(transport.Carrier.organization_id == orgs["carrier"])
    )
    if not carrier:
        transport.profile(
            db,
            ctx,
            CarrierProfileInput(
                dispatch_contact_name="Demo dispatch",
                dispatch_contact_phone_e164="+919876543210",
                directory_visibility="TRADING_PROFILE",
            ),
        )
    vehicles = []
    for index in (1, 2):
        number = f"DEMO-{index}"
        vehicle = db.scalar(
            select(transport.Vehicle).where(
                transport.Vehicle.carrier_organization_id == orgs["carrier"],
                transport.Vehicle.registration_number == number,
            )
        )
        if not vehicle:
            result = transport.vehicle(
                db,
                ctx,
                VehicleInput(
                    registration_number=number,
                    vehicle_type="MEDIUM_TRUCK",
                    declared_payload_capacity_kg="1000",
                    refrigerated=False,
                    declared_hazardous_capable=True,
                ),
            )
            vehicle = db.get(transport.Vehicle, result["id"])
        vehicles.append(vehicle.id)
    reference = f"TT-OPS-{namespace.upper()}"
    trade = db.scalar(select(Trade).where(Trade.reference == reference))
    if not trade:
        facts = demo_facts(orgs["seller"], orgs["buyer"])
        start = now().replace(second=0, microsecond=0) + timedelta(days=2)
        facts["delivery_requirements"].update(
            pickup_earliest_at=start.isoformat(),
            pickup_latest_at=(start + timedelta(hours=4)).isoformat(),
            delivery_deadline_at=(start + timedelta(days=1)).isoformat(),
        )
        facts["items"] = [
            {
                **facts["items"][0],
                "quantity": "100",
                "uqc": "NOS",
                "unit_price_minor": "10000",
                "discount_minor": "0",
            }
        ]
        facts["commercial_terms"]["partial_delivery_allowed"] = True
        ctx = Context(users["seller-operations"], orgs["seller"], uid())
        result = agreements.create_trade(
            db,
            ctx,
            TradeCreate(initiated_by_role="SELLER", facts=facts),
            execution_mode="PRODUCTION" if production else "SIMULATION",
        )
        trade = db.get(Trade, result["trade_id"])
        trade.reference = reference
        ctx.if_match = result["etag"]
        result = agreements.publish(
            db,
            ctx,
            trade.id,
            Publish(
                revision_id=result["current_revision_id"],
                commercial_valid_until=now() + timedelta(days=30),
            ),
        )
        offer = result["active_offer"]
        for side in ("seller", "buyer"):
            agreements.decide(
                db,
                Context(users[f"{side}-approver"], orgs[side], uid()),
                offer["id"],
                Confirmation(revision_id=offer["revision_id"], terms_hash=offer["terms_hash"]),
                "ACCEPT",
            )
    db.commit()
    return {
        "users": {name: u.id for name, u in users.items()},
        "subjects": {name: u.identity_subject for name, u in users.items()},
        "organizations": orgs,
        "trade_id": trade.id,
        "vehicles": vehicles,
        "execution_mode": trade.execution_mode,
    }
