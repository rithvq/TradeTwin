"""Pure validation, exact paise arithmetic and canonical commercial hashes."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext

from pydantic import ValidationError

from .errors import field, pydantic_fields
from .schemas import TradeFacts

MAX_MINOR = 2**63 - 1


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value else "0"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value


def digest(value):
    return hashlib.sha256(
        json.dumps(
            canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def merge(original, changes):
    result = deepcopy(original)
    for key, value in changes.items():
        result[key] = merge(result.get(key) or {}, value) if isinstance(value, dict) else value
    return result


def input_facts(facts):
    result = deepcopy(facts)
    result.pop("initiated_by_role", None)
    for key in ("bill_from", "bill_to"):
        if result.get(key):
            result[key] = {
                name: value
                for name, value in result[key].items()
                if name in {"organization_id", "registration_id", "billing_address"}
            }
    for item in result.get("items") or []:
        for key in (
            "line_no",
            "line_before_discount_minor",
            "line_quoted_total_minor",
            "line_tax_estimate_minor",
        ):
            item.pop(key, None)
    return result


def price(facts):
    errors, totals, taxes = [], [], []
    items = deepcopy(facts.get("items") or [])
    gross_basis = facts.get("pricing_basis") == "GROSS_TAX_INCLUDED"
    with localcontext() as context:
        context.prec = 50
        for index, item in enumerate(items):
            prefix = f"items.{index}"
            if item.get("quantity") is None or item.get("unit_price_minor") is None:
                totals.append(None)
                taxes.append(None)
                continue
            gross = int(
                (Decimal(item["quantity"]) * Decimal(item["unit_price_minor"])).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            discount = int(item.get("discount_minor") or "0")
            total = gross - discount
            if discount > gross:
                errors.append(
                    field(f"{prefix}.discount_minor", "Discount exceeds the pre-discount value")
                )
            if gross > MAX_MINOR or total > MAX_MINOR:
                errors.append(
                    field(f"{prefix}.unit_price_minor", "Amount exceeds supported integer paise")
                )
                total = None
            rate = item.get("declared_tax_rate_percent")
            tax = (
                None
                if gross_basis or rate is None or total is None
                else int(
                    (Decimal(total) * Decimal(rate) / 100).quantize(
                        Decimal("1"), rounding=ROUND_HALF_UP
                    )
                )
            )
            item.update(
                line_before_discount_minor=str(gross),
                line_quoted_total_minor=str(total) if total is not None else None,
                line_tax_estimate_minor=str(tax) if tax is not None else None,
            )
            totals.append(total)
            taxes.append(tax)
    total = sum(totals) if totals and all(value is not None for value in totals) else None
    tax = sum(taxes) if taxes and all(value is not None for value in taxes) else None
    if total is not None and total > MAX_MINOR:
        errors.append(field("items", "Quoted goods value exceeds supported integer paise"))
        total = None
    summary = {
        "currency": "INR",
        "pricing_basis": facts.get("pricing_basis"),
        "quoted_goods_total_minor": str(total) if total is not None else None,
        "complete_tax_estimate_minor": str(tax) if tax is not None else None,
        "freight_estimate_minor": (facts.get("commercial_terms") or {}).get(
            "freight_estimate_minor"
        ),
        "tax_note": "Agreed tax-inclusive goods price; statutory breakdown not determined."
        if gross_basis
        else (
            "Declared rates are estimates pending later validation; unknown tax remains unassessed."
        ),
        "freight_note": "Estimate only, not a confirmed carrier quotation.",
        "final_payable_minor": None,
    }
    return items, summary, errors


def validate_publication(facts, at=None):
    try:
        parsed = TradeFacts.model_validate(input_facts(facts))
    except ValidationError as exc:
        return pydantic_fields(exc.errors())
    errors = []

    def invalid(path, condition, message):
        if condition:
            errors.append(field(path, message))

    invalid(
        "buyer_organization_id",
        parsed.buyer_organization_id == parsed.seller_organization_id,
        "Seller and Buyer must be different organisations",
    )
    invalid(
        "ship_to.state_code",
        parsed.dispatch_from.state_code == parsed.ship_to.state_code,
        "This phase supports interstate goods movement",
    )
    for name in ("dispatch_from", "ship_to"):
        address = getattr(parsed, name)
        invalid(f"{name}.contact_name", not address.contact_name, "Enter the operational contact")
        invalid(
            f"{name}.contact_phone_e164",
            not address.contact_phone_e164,
            "Enter the operational phone",
        )
    for index, item in enumerate(parsed.items):
        prefix = f"items.{index}"
        invalid(
            f"{prefix}.temperature_min_c",
            item.temperature_controlled
            and (
                item.temperature_min_c is None
                or item.temperature_max_c is None
                or item.temperature_min_c > item.temperature_max_c
            ),
            "Enter valid temperature bounds",
        )
        invalid(
            f"{prefix}.hsn_code",
            item.hsn_confirmation != "NOT_PROVIDED" and not item.hsn_code,
            "Provide a code for a declared HSN suggestion or confirmation",
        )
    terms = parsed.commercial_terms
    invalid(
        "commercial_terms.seller_freight_share_percent",
        terms.freight_payer == "SHARED" and terms.seller_freight_share_percent is None,
        "Specify Seller's agreed freight percentage",
    )
    invalid(
        "commercial_terms.insurance_responsibility",
        terms.insurance_required and terms.insurance_responsibility == "NONE",
        "Assign the required insurance responsibility",
    )
    invalid(
        "commercial_terms.advance_minor",
        terms.payment_mode == "ADVANCE" and terms.advance_minor is None,
        "Enter the agreed advance",
    )
    invalid(
        "commercial_terms.credit_days",
        terms.payment_mode == "CREDIT" and terms.credit_days is None,
        "Enter the agreed credit period",
    )
    if terms.payment_mode == "MILESTONE":
        invalid(
            "commercial_terms.milestone_schedule",
            not terms.milestone_schedule
            or sum(item.percent_of_quoted_goods for item in terms.milestone_schedule)
            != Decimal(100),
            "Milestone percentages must total 100",
        )
        for index, milestone in enumerate(terms.milestone_schedule):
            invalid(
                f"commercial_terms.milestone_schedule.{index}.due_on",
                milestone.trigger == "FIXED_DATE" and milestone.due_on is None,
                "Enter the fixed milestone date",
            )
    invalid(
        "commercial_terms.commercial_valid_until",
        terms.commercial_valid_until <= (at or datetime.now(UTC)),
        "Offer expiration must be in the future",
    )
    delivery = parsed.delivery_requirements
    invalid(
        "delivery_requirements.delivery_deadline_at",
        not delivery.pickup_earliest_at
        <= delivery.pickup_latest_at
        <= delivery.delivery_deadline_at,
        "Pickup earliest must precede pickup latest and delivery deadline",
    )
    invalid(
        "delivery_requirements.receiving_window_crosses_midnight",
        (delivery.receiving_window_end_local < delivery.receiving_window_start_local)
        != delivery.receiving_window_crosses_midnight,
        "Explicitly identify a window crossing midnight",
    )
    _, _, pricing_errors = price(facts)
    return errors + pricing_errors
