"""Explicit, isolated demo fixtures. No demo password or login bypass is installed."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from . import agreements, profiles
from .models import Organization, Trade, User, now
from .schemas import Confirmation, MembershipChange, OrganizationDraft, Publish, TradeCreate
from .transactions import Context


def demo_address(state="33", city="Chennai", pin="600001"):
    return {
        "address_line1": "12 Demo Industrial Road",
        "city": city,
        "district": city,
        "state_code": state,
        "postal_code": pin,
        "country_code": "IN",
        "timezone": "Asia/Kolkata",
        "contact_name": "Demonstration contact",
        "contact_phone_e164": "+919876543210",
    }


def demo_profile(name, address):
    return {
        "legal_name": name,
        "entity_type": "COMPANY",
        "authorised_contact_name": "Demo Contact",
        "email": "demo@example.invalid",
        "mobile_e164": "+919876543210",
        "registered_address": address,
        "registration_position": "UNREGISTERED",
        "registration_explanation": "Demonstration declaration only; not a tax eligibility claim.",
    }


def demo_facts(seller, buyer):
    start = now() + timedelta(days=2)
    origin, destination = demo_address(), demo_address("29", "Bengaluru", "560001")
    line = {
        "description": "Cotton shirts",
        "specification": "Demo boxed cotton shirts, size M",
        "hsn_confirmation": "NOT_PROVIDED",
        "quantity": "10.000000",
        "uqc": "PCS",
        "unit_price_minor": "12500.000000",
        "discount_minor": "500",
        "hazardous_declared": False,
        "temperature_controlled": False,
        "fragile": False,
        "stackable": True,
    }
    return {
        "scope": "DOMESTIC_INTERSTATE",
        "movement_purpose": "SALE",
        "seller_organization_id": seller,
        "buyer_organization_id": buyer,
        "bill_from": {"organization_id": seller, "billing_address": origin},
        "bill_to": {"organization_id": buyer, "billing_address": destination},
        "dispatch_from": origin,
        "ship_to": destination,
        "transaction_layout": "REGULAR",
        "currency": "INR",
        "pricing_basis": "NET_TAX_EXTRA",
        "tax_terms": "Tax settlement subject to later validation; no final payable determined.",
        "items": [
            line,
            {
                **line,
                "description": "Stationery",
                "specification": "Demo notebooks",
                "quantity": "2.500000",
                "unit_price_minor": "3999.000000",
                "discount_minor": "0",
            },
        ],
        "commercial_terms": {
            "freight_payer": "SELLER",
            "freight_included_in_goods_price": False,
            "loading_responsibility": "SELLER",
            "unloading_responsibility": "BUYER",
            "insurance_required": False,
            "insurance_responsibility": "NONE",
            "payment_mode": "ON_DELIVERY",
            "acceptance_window_hours": 48,
            "quality_acceptance_criteria": "Goods match agreed specification",
            "return_policy": "Report defects within 48 hours",
            "cancellation_terms": "Mutual agreement required",
            "partial_delivery_allowed": False,
            "supplier_substitution_allowed": False,
            "pickup_location_substitution_allowed": False,
            "commercial_valid_until": (start + timedelta(days=7)).isoformat(),
        },
        "delivery_requirements": {
            "mode": "ROAD",
            "pickup_earliest_at": start.isoformat(),
            "pickup_latest_at": (start + timedelta(hours=4)).isoformat(),
            "delivery_deadline_at": (start + timedelta(days=1)).isoformat(),
            "receiving_window_start_local": "09:00",
            "receiving_window_end_local": "18:00",
            "receiving_timezone": "Asia/Kolkata",
            "receiving_window_crosses_midnight": False,
            "consolidation_allowed": False,
            "return_truck_allowed": False,
            "maximum_transshipments": 0,
        },
    }


def seed_demo(db, subjects=None):
    subjects = subjects or {}
    users = {}
    for name in (
        "seller-operator",
        "seller-approver",
        "buyer-operator",
        "buyer-approver",
        "unrelated",
    ):
        subject = subjects.get(name, f"commercial-demo:{name}")
        user = db.scalar(select(User).where(User.identity_subject == subject))
        if not user:
            user = User(
                id=str(uuid5(NAMESPACE_URL, f"tradetwin:{subject}")),
                identity_subject=subject,
                display_name=name,
                email=f"{name}@example.invalid",
            )
            db.add(user)
            db.flush()
        users[name] = user
    orgs = {}
    for name, owner, values in (
        ("seller", "seller-operator", demo_profile("Demo Tamil Nadu Seller", demo_address())),
        (
            "buyer",
            "buyer-operator",
            demo_profile("Demo Karnataka Buyer", demo_address("29", "Bengaluru", "560001")),
        ),
        (
            "unrelated",
            "unrelated",
            demo_profile("Demo Unrelated Business", demo_address("27", "Pune", "411001")),
        ),
    ):
        org = db.scalar(select(Organization).where(Organization.legal_name == values["legal_name"]))
        ctx = Context(users[owner], None, str(uuid5(NAMESPACE_URL, f"seed:{name}")))
        if not org:
            result = profiles.create_organization(db, ctx, OrganizationDraft.model_validate(values))
            org = db.get(Organization, result["organization_id"])
        orgs[name] = org.id
    for name, org_name, capabilities in (
        ("seller-operator", "seller", ["ORG_ADMIN", "SELLER_OPERATOR"]),
        ("seller-approver", "seller", ["SELLER_APPROVER"]),
        ("buyer-operator", "buyer", ["ORG_ADMIN", "BUYER_OPERATOR"]),
        ("buyer-approver", "buyer", ["BUYER_APPROVER"]),
        ("unrelated", "unrelated", ["ORG_ADMIN", "SELLER_OPERATOR", "BUYER_OPERATOR"]),
    ):
        owner = users[
            "seller-operator"
            if org_name == "seller"
            else "buyer-operator"
            if org_name == "buyer"
            else "unrelated"
        ]
        ctx = Context(owner, orgs[org_name], str(uuid5(NAMESPACE_URL, f"seed-role:{name}")))
        profiles.change_membership(
            db,
            ctx,
            orgs[org_name],
            MembershipChange(user_id=users[name].id, capabilities=capabilities),
        )
    fixtures = {
        "users": {name: user.id for name, user in users.items()},
        "subjects": {name: user.identity_subject for name, user in users.items()},
        "organizations": orgs,
        "trades": {},
    }
    for status in ("DRAFT", "OFFERED", "CONFIRMED"):
        reference = f"TT-COM-DEMO-{status}"
        trade = db.scalar(select(Trade).where(Trade.reference == reference))
        if not trade:
            ctx = Context(
                users["seller-operator"], orgs["seller"], str(uuid5(NAMESPACE_URL, reference))
            )
            view = agreements.create_trade(
                db,
                ctx,
                TradeCreate(
                    initiated_by_role="SELLER", facts=demo_facts(orgs["seller"], orgs["buyer"])
                ),
            )
            trade = db.get(Trade, view["trade_id"])
            trade.reference = reference
            if status != "DRAFT":
                ctx.if_match = view["etag"]
                view = agreements.publish(
                    db,
                    ctx,
                    trade.id,
                    Publish(
                        revision_id=view["current_revision_id"],
                        commercial_valid_until=now() + timedelta(days=7),
                    ),
                )
                if status == "CONFIRMED":
                    for side in ("seller", "buyer"):
                        decision_ctx = Context(
                            users[f"{side}-approver"],
                            orgs[side],
                            str(uuid5(NAMESPACE_URL, f"{reference}:{side}")),
                        )
                        offer = view["active_offer"]
                        agreements.decide(
                            db,
                            decision_ctx,
                            offer["id"],
                            Confirmation(
                                revision_id=offer["revision_id"], terms_hash=offer["terms_hash"]
                            ),
                            "ACCEPT",
                        )
        fixtures["trades"][status] = trade.id
    db.commit()
    return fixtures
