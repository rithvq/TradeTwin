"""Append-only commercial revisions, snapshots and redacted evidence."""

import re
from copy import deepcopy
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import func, select

from .access import aware, participant_role
from .errors import TradeError, field, pydantic_fields
from .models import (
    Amendment,
    Approval,
    Audit,
    Item,
    Offer,
    Organization,
    Participant,
    Registration,
    Revision,
    Snapshot,
    now,
    uid,
)
from .schemas import Address, OrganizationFields
from .terms import digest, input_facts, price, validate_publication


def audit(db, ctx, action, subject, trade=None, revision=None, summary=None, consignment=None):
    def redact(value):
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str):
            value = re.sub(
                r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b",
                "[registration redacted]",
                value,
                flags=re.I,
            )
            value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email redacted]", value)
            return re.sub(r"(?<![\w-])\+?\d{10,18}(?![\w-])", "[identifier redacted]", value)
        return value

    db.add(
        Audit(
            actor_user_id=ctx.user.id,
            actor_organization_id=ctx.org_id,
            action=action,
            subject_type=type(subject).__name__,
            subject_id=subject.id,
            trade_id=trade.id if trade else None,
            revision_id=revision.id if revision else None,
            terms_hash=revision.terms_hash if revision else None,
            request_id=ctx.request_id,
            redacted_summary_json=redact(summary or {}),
            consignment_id=consignment.id if consignment else None,
            execution_mode=trade.execution_mode if trade else "PRODUCTION",
        )
    )


def registration(db, registration_id, org_id, path="registration_id"):
    row = db.get(Registration, str(registration_id)) if registration_id else None
    if registration_id and (not row or row.organization_id != org_id):
        raise TradeError(
            "VALIDATION_FAILED",
            "Registration is not available to this party.",
            fields=[field(path, "Select this organisation's registration")],
        )
    return row


def profile_values(org):
    return {name: getattr(org, name) for name in OrganizationFields.model_fields}


def profile_errors(org):
    try:
        OrganizationFields.model_validate(profile_values(org))
        return []
    except ValidationError as exc:
        errors = pydantic_fields(exc.errors())
        for error in errors:
            if not error["path"]:
                error["path"] = "registration_explanation"
        return errors


def resolve_parties(db, trade, facts, actor_org, complete=False):
    result = deepcopy(facts)
    errors = []
    own_key = f"{trade.initiated_by_role.lower()}_organization_id"
    if not trade.accepted_revision_id and result.get(own_key) != trade.creator_organization_id:
        raise TradeError("FORBIDDEN", "The initiating party must be your organisation.", 403)
    for role, key in (("SELLER", "bill_from"), ("BUYER", "bill_to")):
        org_id = result.get(f"{role.lower()}_organization_id")
        if not org_id:
            continue
        org = db.get(Organization, org_id)
        if not org:
            errors.append(
                field(f"{role.lower()}_organization_id", "Select an onboarded organisation")
            )
            continue
        if complete:
            errors.extend(
                {**item, "path": f"{role.lower()}_profile.{item['path']}"}
                for item in profile_errors(org)
            )
        reg_id = result.get(f"{role.lower()}_registration_id")
        party = result.get(key) or {}
        if party.get("organization_id") not in {None, org_id} or party.get(
            "registration_id"
        ) not in {None, reg_id}:
            errors.append(
                field(key, "Party references must match the selected organisation/registration")
            )
        reg = registration(db, reg_id, org_id, f"{role.lower()}_registration_id")
        if complete and org.registration_position == "REGISTERED" and not reg:
            errors.append(
                field(f"{role.lower()}_registration_id", "Choose the declared GST registration")
            )
        address = org.registered_address if org_id == actor_org else party.get("billing_address")
        # Own billing details are a profile snapshot, never a client-supplied identity.
        if complete and not address:
            errors.append(field(f"{key}.billing_address", "Propose a billing address for review"))
        if complete:
            if address:
                try:
                    address = Address.model_validate(address).model_dump(mode="json")
                except ValidationError as exc:
                    errors.extend(
                        {**item, "path": f"{key}.billing_address.{item['path']}"}
                        for item in pydantic_fields(exc.errors())
                    )
            result[key] = {
                "organization_id": org_id,
                "registration_id": reg_id,
                "legal_name": org.legal_name,
                "trade_name": org.trade_name,
                "registration_position": org.registration_position,
                "gstin": reg.gstin if reg else None,
                "declared_taxpayer_scheme": reg.declared_taxpayer_scheme if reg else None,
                "billing_address": address,
                "snapshot_source": "ORGANISATION_PROFILE"
                if org_id == actor_org
                else "PROPOSED_BY_COUNTERPARTY",
            }
        else:
            result[key] = {
                "organization_id": org_id,
                "registration_id": reg_id,
                "billing_address": address,
            }
    if errors and complete:
        raise TradeError(
            "VALIDATION_FAILED", "Complete the parties before publishing.", fields=errors
        )
    if errors:
        raise TradeError("VALIDATION_FAILED", "Check the selected parties.", fields=errors)
    seller, buyer = result.get("seller_organization_id"), result.get("buyer_organization_id")
    if seller and buyer and seller == buyer:
        raise TradeError(
            "VALIDATION_FAILED",
            "Seller and Buyer must differ.",
            fields=[field("buyer_organization_id", "Choose a different organisation")],
        )
    if complete:
        existing = {
            row.participant_role: row
            for row in db.scalars(select(Participant).where(Participant.trade_id == trade.id))
        }
        for role, org_id in (("SELLER", seller), ("BUYER", buyer)):
            if role in existing and existing[role].organization_id != org_id:
                if trade.accepted_revision_id:
                    raise TradeError(
                        "VALIDATION_FAILED", "Phase 1 amendments cannot replace a party."
                    )
                existing[role].organization_id = org_id
            elif role not in existing:
                db.add(
                    Participant(trade_id=trade.id, organization_id=org_id, participant_role=role)
                )
        db.flush()
    return result


def revision_facts(db, revision, derived=True):
    facts = deepcopy(revision.facts_json)
    items = []
    for row in db.scalars(
        select(Item).where(Item.trade_revision_id == revision.id).order_by(Item.line_no)
    ):
        item = deepcopy(row.cargo_declarations_json)
        item.update(
            line_ref=row.line_ref,
            line_no=row.line_no,
            description=row.description,
            specification=row.specification,
            hsn_code=row.hsn_code,
            hsn_confirmation=row.hsn_confirmation,
            uqc=row.uqc,
            quantity=format(row.quantity, ".6f") if row.quantity is not None else None,
            unit_price_minor=format(row.unit_price_minor, ".6f")
            if row.unit_price_minor is not None
            else None,
            discount_minor=str(row.discount_minor),
            declared_tax_rate_percent=str(row.declared_tax_rate_percent)
            if row.declared_tax_rate_percent is not None
            else None,
        )
        for name in (
            "line_before_discount_minor",
            "line_quoted_total_minor",
            "line_tax_estimate_minor",
        ):
            item[name] = str(getattr(row, name)) if getattr(row, name) is not None else None
        items.append(item)
    facts["items"] = items
    return facts if derived else input_facts(facts)


def make_revision(db, ctx, trade, facts, kind="DRAFT", supersedes=None):
    result = deepcopy(facts)
    previous = db.get(Revision, supersedes) if supersedes else None
    retained = (
        {item["line_ref"] for item in revision_facts(db, previous).get("items", [])}
        if previous
        else set()
    )
    seen = set()
    for index, item in enumerate(result.get("items") or []):
        line_ref = item.get("line_ref")
        if line_ref and line_ref not in retained:
            raise TradeError(
                "VALIDATION_FAILED",
                "New lines receive server-generated references.",
                fields=[field(f"items.{index}.line_ref", "Use only a retained line reference")],
            )
        item["line_ref"] = line_ref or uid()
        if item["line_ref"] in seen:
            raise TradeError("VALIDATION_FAILED", "Goods line references must be unique.")
        seen.add(item["line_ref"])
        item["line_no"] = index + 1
    items, summary, errors = price(result)
    if errors:
        raise TradeError("VALIDATION_FAILED", "Check the quoted values.", fields=errors)
    snapshots = {}
    if kind != "DRAFT":
        for role, key in (("SELLER", "bill_from"), ("BUYER", "bill_to")):
            snapshot = Snapshot(
                id=uid(),
                trade_id=trade.id,
                participant_role=role,
                organization_id=result[key]["organization_id"],
                snapshot_json=result[key],
                content_hash=digest(result[key]),
            )
            db.add(snapshot)
            snapshots[role] = snapshot.id
        db.flush()
    # Hash values, not line/revision identity or derived estimates.
    hash_facts = input_facts(result)
    for key in ("bill_from", "bill_to"):
        if kind != "DRAFT":
            hash_facts[key] = result[key]
            hash_facts[key] = {
                name: value for name, value in hash_facts[key].items() if name != "snapshot_source"
            }
    for item in hash_facts.get("items") or []:
        item.pop("line_ref", None)
        item["discount_minor"] = str(int(item.get("discount_minor") or 0))
        for name in (
            "quantity",
            "unit_price_minor",
            "declared_tax_rate_percent",
            "estimated_gross_weight_kg",
            "temperature_min_c",
            "temperature_max_c",
        ):
            if item.get(name) is not None:
                item[name] = Decimal(item[name])
    terms = hash_facts.get("commercial_terms") or {}
    for name in ("advance_minor", "freight_estimate_minor"):
        if terms.get(name) is not None:
            terms[name] = str(int(terms[name]))
    for name in ("seller_freight_share_percent",):
        if terms.get(name) is not None:
            terms[name] = Decimal(terms[name])
    for milestone in terms.get("milestone_schedule") or []:
        milestone["percent_of_quoted_goods"] = Decimal(milestone["percent_of_quoted_goods"])
    number = (
        db.scalar(select(func.max(Revision.revision_number)).where(Revision.trade_id == trade.id))
        or 0
    ) + 1
    revision = Revision(
        id=uid(),
        trade_id=trade.id,
        revision_number=number,
        revision_kind=kind,
        seller_snapshot_id=snapshots.get("SELLER"),
        buyer_snapshot_id=snapshots.get("BUYER"),
        facts_json={key: value for key, value in result.items() if key != "items"},
        pricing_summary_json=summary,
        terms_hash=digest(hash_facts),
        supersedes_revision_id=supersedes,
        created_by=ctx.user.id,
    )
    db.add(revision)
    db.flush()
    cargo_keys = {
        "estimated_gross_weight_kg",
        "package_count_estimate",
        "hazardous_declared",
        "temperature_controlled",
        "temperature_min_c",
        "temperature_max_c",
        "fragile",
        "stackable",
    }
    columns = {
        "description",
        "specification",
        "hsn_code",
        "hsn_confirmation",
        "quantity",
        "uqc",
        "unit_price_minor",
        "discount_minor",
        "declared_tax_rate_percent",
        "line_before_discount_minor",
        "line_quoted_total_minor",
        "line_tax_estimate_minor",
    }
    for item in items:
        values = {key: item.get(key) for key in columns}
        values["discount_minor"] = int(values["discount_minor"] or 0)
        db.add(
            Item(
                trade_revision_id=revision.id,
                line_ref=item["line_ref"],
                line_no=item["line_no"],
                cargo_declarations_json={key: item.get(key) for key in cargo_keys},
                **values,
            )
        )
    db.flush()
    trade.current_revision_id = revision.id
    return revision


def revision_view(db, revision_id):
    revision = db.get(Revision, revision_id) if revision_id else None
    if not revision:
        return None
    return {
        "id": revision.id,
        "revision_number": revision.revision_number,
        "revision_kind": revision.revision_kind,
        "facts": revision_facts(db, revision),
        "pricing_summary": revision.pricing_summary_json,
        "terms_hash": revision.terms_hash,
        "created_at": aware(revision.created_at).isoformat(),
    }


def approvals(db, offer):
    if not offer:
        return []
    rows = {
        row.participant_role: row
        for row in db.scalars(select(Approval).where(Approval.offer_id == offer.id))
    }
    return [
        {
            "party_role": role,
            "decision": rows[role].decision if role in rows else "PENDING",
            "decided_at": aware(rows[role].decided_at).isoformat() if role in rows else None,
        }
        for role in ("SELLER", "BUYER")
    ]


def trade_view(db, ctx, trade):
    accepted = revision_view(db, trade.accepted_revision_id)
    current = revision_view(db, trade.current_revision_id)
    offer = db.get(Offer, trade.active_offer_id) if trade.active_offer_id else None
    amendment = (
        db.get(Amendment, trade.pending_amendment_id) if trade.pending_amendment_id else None
    )
    side = participant_role(db, trade.id, ctx.org_id)
    candidate_visible = (
        not amendment
        or amendment.status != "DRAFT"
        or amendment.proposer_organization_id == ctx.org_id
    )
    if (
        not trade.accepted_revision_id
        and trade.agreement_status == "DRAFT"
        and ctx.org_id != trade.creator_organization_id
    ):
        candidate_visible = False
    current = current if candidate_visible else None
    expired = bool(offer and offer.status == "ACTIVE" and aware(offer.expires_at) <= now())
    from .access import grants, membership

    permissions = grants(db, membership(db, ctx.user, ctx.org_id), trade.id)

    def has(permission):
        return any(
            grant.permission_code == permission and grant.capability.startswith(f"{side}_")
            for grant in permissions
        )

    actions = []
    progress = approvals(db, offer)
    own_pending = any(
        item["party_role"] == side and item["decision"] == "PENDING" for item in progress
    )
    if (
        offer
        and offer.status == "ACTIVE"
        and not expired
        and own_pending
        and has(f"order.confirm.{side.lower()}")
    ):
        actions.extend(["ACCEPT", "REJECT"])
    if (
        offer
        and offer.status == "ACTIVE"
        and offer.published_by_organization_id == ctx.org_id
        and has("trade.withdraw_offer")
    ):
        actions.append("WITHDRAW")
    if (
        trade.agreement_status == "DRAFT"
        and ctx.org_id == trade.creator_organization_id
        and has("trade.edit_draft")
    ):
        actions.extend(["EDIT_DRAFT", "PUBLISH"])
    if trade.accepted_revision_id and not amendment and has("trade.propose_amendment"):
        actions.append("PROPOSE_AMENDMENT")
    if (
        amendment
        and amendment.proposer_organization_id == ctx.org_id
        and has("trade.propose_amendment")
    ):
        actions.append("WITHDRAW_AMENDMENT")
        if amendment.status == "DRAFT":
            actions.extend(["EDIT_AMENDMENT", "PUBLISH_AMENDMENT"])
    primary = accepted or current
    counterparty_id = (
        (primary or {})
        .get("facts", {})
        .get("buyer_organization_id" if side == "SELLER" else "seller_organization_id")
    )
    counterparty = db.get(Organization, counterparty_id) if counterparty_id else None
    owners = []
    if offer and not expired:
        for item in progress:
            if item["decision"] == "PENDING":
                owners.append(
                    {
                        "participant_role": item["party_role"],
                        "capability": f"{item['party_role']}_APPROVER",
                        "action": "REVIEW_OFFER",
                    }
                )
    elif expired:
        owner_role = participant_role(db, trade.id, offer.published_by_organization_id)
        owners.append(
            {
                "participant_role": owner_role,
                "capability": f"{owner_role}_OPERATOR",
                "action": "REPLACE_EXPIRED_OFFER",
            }
        )
    elif not trade.accepted_revision_id or (amendment and amendment.status == "DRAFT"):
        owner = amendment.proposer_organization_id if amendment else trade.creator_organization_id
        owner_role = participant_role(db, trade.id, owner)
        owners.append(
            {
                "participant_role": owner_role,
                "capability": f"{owner_role}_OPERATOR",
                "action": "PREPARE_OFFER",
            }
        )
    return {
        "trade_id": trade.id,
        "reference": trade.reference,
        "execution_mode": trade.execution_mode,
        "agreement_status": trade.agreement_status,
        "accepted_revision": accepted,
        "current_candidate_revision": current,
        "current_revision_id": current["id"] if current else None,
        "revision_number": current["revision_number"] if current else 0,
        "active_offer": {
            "id": offer.id,
            "revision_id": offer.revision_id,
            "status": "EXPIRED" if expired else offer.status,
            "purpose": offer.purpose,
            "expires_at": aware(offer.expires_at).isoformat(),
            "published_by_organization_id": offer.published_by_organization_id,
            "terms_hash": db.get(Revision, offer.revision_id).terms_hash,
        }
        if offer
        else None,
        "pending_amendment": {
            "id": amendment.id,
            "status": amendment.status,
            "reason": amendment.reason,
            "base_accepted_revision_id": amendment.base_accepted_revision_id,
            "proposed_revision_id": amendment.proposed_revision_id if candidate_visible else None,
            "proposer_organization_id": amendment.proposer_organization_id,
        }
        if amendment
        else None,
        "approval_progress": progress
        if offer
        else approvals(
            db,
            db.scalar(
                select(Offer).where(
                    Offer.trade_id == trade.id,
                    Offer.status == "ACCEPTED",
                    Offer.revision_id == trade.accepted_revision_id,
                )
            ),
        ),
        "pricing_summary": primary["pricing_summary"] if primary else {},
        "next_actions": actions,
        "next_action_owners": owners,
        "counterparty": {
            "organization_id": counterparty.id,
            "legal_name": counterparty.legal_name,
            "trade_name": counterparty.trade_name,
        }
        if counterparty
        else None,
        "validation_errors": validate_publication(current["facts"]) if current else [],
        "dispatch_readiness": "NOT_ASSESSED",
        "etag": f'"{trade.row_version}"',
    }
