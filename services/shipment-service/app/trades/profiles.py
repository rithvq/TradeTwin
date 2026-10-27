from sqlalchemy import or_, select

from .access import organization, require, trade_access
from .errors import TradeError
from .ledger import audit, profile_errors, profile_values, registration
from .models import Grant, Location, Membership, Organization, Registration, User, now, uid
from .reference import ROLE_PERMISSIONS


def profile_view(db, org):
    missing = profile_errors(org)
    return {
        "organization_id": org.id,
        **profile_values(org),
        "profile_status": org.profile_status,
        "missing_fields": missing,
        "etag": f'"{org.row_version}"',
        "registrations": [
            {
                "id": row.id,
                "gstin": row.gstin,
                "state_code": row.state_code,
                "declared_taxpayer_scheme": row.declared_taxpayer_scheme,
                "declared_establishment_kind": row.declared_establishment_kind,
                "source": row.source,
                "verification_status": row.verification_status,
                "verified_at": None,
                "existing_verification_reference": None,
            }
            for row in db.scalars(
                select(Registration).where(Registration.organization_id == org.id)
            )
        ],
        "locations": [
            {
                "id": row.id,
                "registration_id": row.registration_id,
                "label": row.label,
                "location_type": row.location_type,
                "address": row.address,
                "visibility": row.visibility,
                "active": row.active,
            }
            for row in db.scalars(select(Location).where(Location.organization_id == org.id))
        ],
    }


def add_grants(db, member, capabilities, trade_id=None, expires_at=None):
    for capability in capabilities:
        for permission in ROLE_PERMISSIONS[capability]:
            db.add(
                Grant(
                    membership_id=member.id,
                    capability=capability,
                    permission_code=permission,
                    trade_id=trade_id,
                    expires_at=expires_at,
                )
            )


def create_organization(db, ctx, payload):
    values = payload.model_dump(mode="json", exclude_unset=True)
    org = Organization(id=uid(), created_by=ctx.user.id, **values)
    org.profile_status = "COMPLETE" if not profile_errors(org) else "DRAFT"
    db.add(org)
    db.flush()
    member = Membership(
        id=uid(), organization_id=org.id, user_id=ctx.user.id, created_by=ctx.user.id
    )
    db.add(member)
    db.flush()
    add_grants(db, member, ["ORG_ADMIN"])
    ctx.org_id = org.id
    audit(
        db,
        ctx,
        "ORGANIZATION_CREATED",
        org,
        summary={"after": "Administrator membership only; no commercial approval granted"},
    )
    db.flush()
    return profile_view(db, org)


def edit_organization(db, ctx, org_id, payload):
    from .agreements import match
    from .terms import merge

    org = organization(db, ctx.user, org_id, "organization.edit", lock=True)
    match(ctx, org)
    changes = payload.model_dump(mode="json", exclude_unset=True)
    for key, value in changes.items():
        setattr(
            org,
            key,
            merge(org.registered_address or {}, value)
            if key == "registered_address" and value
            else value,
        )
    org.profile_status = "COMPLETE" if not profile_errors(org) else "DRAFT"
    org.row_version += 1
    audit(db, ctx, "ORGANIZATION_EDITED", org, summary={"changed_fields": sorted(changes)})
    db.flush()
    return profile_view(db, org)


def add_registration(db, ctx, org_id, payload):
    organization(db, ctx.user, org_id, "organization.edit")
    if db.scalar(select(Registration).where(Registration.gstin == payload.gstin)):
        raise TradeError(
            "REGISTRATION_COLLISION",
            "This registration is already recorded. No membership or ownership is transferred.",
            409,
        )
    row = Registration(
        id=uid(), organization_id=org_id, created_by=ctx.user.id, **payload.model_dump()
    )
    db.add(row)
    db.flush()
    audit(
        db,
        ctx,
        "REGISTRATION_DECLARED",
        row,
        summary={"verification_status": "FORMAT_VALIDATED", "authority_verified": False},
    )
    return {
        "id": row.id,
        "organization_id": org_id,
        **payload.model_dump(),
        "source": "SELF_DECLARED",
        "verification_status": "FORMAT_VALIDATED",
        "verified_at": None,
    }


def add_location(db, ctx, org_id, payload):
    organization(db, ctx.user, org_id, "locations.manage")
    registration(db, payload.registration_id, org_id)
    row = Location(
        id=uid(), organization_id=org_id, created_by=ctx.user.id, **payload.model_dump(mode="json")
    )
    db.add(row)
    db.flush()
    audit(db, ctx, "LOCATION_CREATED", row, summary={"visibility": row.visibility})
    return {
        "id": row.id,
        "organization_id": org_id,
        **payload.model_dump(mode="json"),
        "active": True,
    }


def change_membership(db, ctx, org_id, payload):
    require(db, ctx.user, org_id, "members.manage")
    target = db.get(User, str(payload.user_id))
    if not target or not target.active:
        raise TradeError(
            "NOT_FOUND", "The member must first sign in to TradeTwin and share their user ID.", 404
        )
    if payload.trade_id:
        trade_access(db, ctx.user, org_id, str(payload.trade_id), "trade.read")
    member = db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == target.id
        )
    )
    if not member:
        member = Membership(
            id=uid(), organization_id=org_id, user_id=target.id, created_by=ctx.user.id
        )
        db.add(member)
        db.flush()
    member.status = payload.status
    # Replace only the requested scope; preserve separate trade-specific grants.
    for grant in db.scalars(
        select(Grant).where(
            Grant.membership_id == member.id,
            Grant.trade_id == (str(payload.trade_id) if payload.trade_id else None),
            Grant.revoked_at.is_(None),
        )
    ):
        grant.revoked_at = now()
    add_grants(
        db,
        member,
        payload.capabilities,
        str(payload.trade_id) if payload.trade_id else None,
        payload.expires_at,
    )
    audit(
        db,
        ctx,
        "MEMBERSHIP_CAPABILITIES_CHANGED",
        member,
        summary={
            "capabilities": payload.capabilities,
            "status": payload.status,
            "trade_scoped": bool(payload.trade_id),
        },
    )
    db.flush()
    return {
        "membership_id": member.id,
        "user_id": target.id,
        "status": member.status,
        "capabilities": payload.capabilities,
        "trade_id": str(payload.trade_id) if payload.trade_id else None,
    }


def me(db, user):
    memberships = []
    for member in db.scalars(
        select(Membership).where(Membership.user_id == user.id, Membership.status == "ACTIVE")
    ):
        org = db.get(Organization, member.organization_id)
        active = list(
            db.scalars(
                select(Grant).where(Grant.membership_id == member.id, Grant.revoked_at.is_(None))
            )
        )
        from .access import aware

        active = [
            grant for grant in active if not grant.expires_at or aware(grant.expires_at) > now()
        ]
        memberships.append(
            {
                "organization_id": org.id,
                "legal_name": org.legal_name,
                "profile_status": org.profile_status,
                "capabilities": sorted({row.capability for row in active}),
                "permissions": [
                    {
                        "permission_code": row.permission_code,
                        "trade_id": row.trade_id,
                        "capability": row.capability,
                    }
                    for row in active
                ],
                "registrations": [
                    {
                        "id": row.id,
                        "gstin": row.gstin,
                        "state_code": row.state_code,
                        "verification_status": row.verification_status,
                    }
                    for row in db.scalars(
                        select(Registration).where(Registration.organization_id == org.id)
                    )
                ],
                "available_interface_roles": [
                    role
                    for role in ("SELLER", "BUYER")
                    if any(row.capability.startswith(f"{role}_") for row in active)
                ],
            }
        )
    return {
        "user": {"id": user.id, "display_name": user.display_name, "email": user.email},
        "memberships": memberships,
        "available_interface_roles": ["SELLER", "BUYER"],
    }


def trading_partners(db, query):
    rows = db.scalars(
        select(Organization)
        .where(
            Organization.profile_status == "COMPLETE",
            ~select(User.id)
            .where(
                User.id == Organization.created_by,
                User.identity_subject.like("operations-demo:phase4-appdemo-%"),
            )
            .exists(),
            or_(
                Organization.legal_name.ilike(f"%{query[:100]}%"),
                Organization.trade_name.ilike(f"%{query[:100]}%"),
                select(Registration.id)
                .where(
                    Registration.organization_id == Organization.id,
                    Registration.gstin.ilike(f"%{query[:100]}%"),
                )
                .exists(),
            ),
        )
        .order_by(Organization.legal_name)
        .limit(30)
    )
    return [
        {
            "organization_id": org.id,
            "legal_name": org.legal_name,
            "trade_name": org.trade_name,
            "registration_position": org.registration_position,
            "registrations": [
                {
                    "id": row.id,
                    "gstin": row.gstin,
                    "state_code": row.state_code,
                    "verification_status": row.verification_status,
                }
                for row in db.scalars(
                    select(Registration).where(Registration.organization_id == org.id)
                )
            ],
            "trading_locations": [
                {"id": row.id, "label": row.label, "address": row.address}
                for row in db.scalars(
                    select(Location).where(
                        Location.organization_id == org.id,
                        Location.visibility == "TRADING_PROFILE",
                        Location.active.is_(True),
                    )
                )
            ],
        }
        for org in rows
    ]
