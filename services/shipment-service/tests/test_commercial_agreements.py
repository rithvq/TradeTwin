import os
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from tradetwin_security import identity

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app.database import get_db  # noqa: E402
from app.trades.demo import demo_address, demo_facts, seed_demo  # noqa: E402
from app.trades.errors import install_handlers  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import Approval, Grant, Membership, Offer, Revision, now  # noqa: E402
from app.trades.router import router  # noqa: E402
from app.trades.schemas import gstin_format  # noqa: E402
from app.trades.terms import price  # noqa: E402


@pytest.fixture()
def env(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    # Optional PostgreSQL suite uses a disposable, random schema, never production tables.
    engine = create_engine(
        url or f"sqlite+pysqlite:///{tmp_path / 'agreements.db'}",
        connect_args={} if url else {"check_same_thread": False},
    )
    schema = f"trade_test_{uuid4().hex}" if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    migrate(engine)
    migrate(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        fixtures = seed_demo(db)
    application = FastAPI()
    install_handlers(application)
    application.include_router(router)

    def dependency():
        with sessions() as db:
            yield db

    application.dependency_overrides[get_db] = dependency

    @application.middleware("http")
    async def test_identity(request, call_next):
        # This fixture authentication exists only in tests, never in the application.
        name = request.headers.get("X-Test-User")
        token = identity.set(
            {"id": fixtures["subjects"][name], "name": name, "email": "fixture@example.invalid"}
            if name
            else None
        )
        try:
            return await call_next(request)
        finally:
            identity.reset(token)

    with TestClient(application) as client:
        yield client, fixtures, sessions, bool(url)
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


def headers(fixtures, user="seller-operator", org="seller", etag=None, key=None):
    result = {
        "X-Test-User": user,
        "X-Organization-Id": fixtures["organizations"][org],
        "Idempotency-Key": key or str(uuid4()),
    }
    if etag:
        result["If-Match"] = etag
    return result


def fetch(env, trade_id=None, user="seller-operator", org="seller"):
    client, fixtures, *_ = env
    response = client.get(
        f"/api/v1/trades/{trade_id or fixtures['trades']['DRAFT']}",
        headers=headers(fixtures, user, org),
    )
    assert response.status_code == 200, response.text
    return response.json()


def create(env, facts=None, key=None):
    client, fixtures, *_ = env
    response = client.post(
        "/api/v1/trades",
        headers=headers(fixtures, key=key),
        json={"initiated_by_role": "SELLER", "facts": facts or {}},
    )
    assert response.status_code == 201, response.text
    return response.json()


def publish(env, view):
    client, fixtures, *_ = env
    return client.post(
        f"/api/v1/trades/{view['trade_id']}/offers",
        headers=headers(fixtures, etag=view["etag"]),
        json={
            "revision_id": view["current_revision_id"],
            "commercial_valid_until": (now() + timedelta(days=7)).isoformat(),
        },
    )


def decision(env, view, side="seller", reject=False, hash_value=None, revision=None, key=None):
    client, fixtures, *_ = env
    offer = view["active_offer"]
    body = {
        "revision_id": revision or offer["revision_id"],
        "terms_hash": hash_value or offer["terms_hash"],
    }
    if reject:
        body["reason"] = "Proposed terms not acceptable"
    return client.post(
        f"/api/v1/offers/{offer['id']}/{'rejections' if reject else 'confirmations'}",
        headers=headers(fixtures, f"{side}-approver", side, key=key),
        json=body,
    )


def test_complete_agreement_and_amendment_demonstration(env):
    client, fixtures, *_ = env
    facts = demo_facts(fixtures["organizations"]["seller"], fixtures["organizations"]["buyer"])
    view = create(env, facts)
    response = publish(env, view)
    assert response.status_code == 200, response.text
    offered = response.json()
    assert all(row["decision"] == "PENDING" for row in offered["approval_progress"])
    assert decision(env, offered).json()["agreement_status"] == "OFFERED"
    assert decision(env, offered, "buyer").json()["agreement_status"] == "CONFIRMED"
    confirmed = fetch(env, view["trade_id"])
    accepted_id = confirmed["accepted_revision"]["id"]
    response = client.post(
        f"/api/v1/trades/{view['trade_id']}/amendments",
        headers=headers(fixtures, "buyer-operator", "buyer", confirmed["etag"]),
        json={"base_accepted_revision_id": accepted_id, "reason": "Adjust quantity"},
    )
    assert response.status_code == 200, response.text
    amended = response.json()
    assert amended["accepted_revision"]["id"] == accepted_id
    items = deepcopy(amended["current_candidate_revision"]["facts"]["items"])
    for item in items:
        for name in (
            "line_no",
            "line_before_discount_minor",
            "line_quoted_total_minor",
            "line_tax_estimate_minor",
        ):
            item.pop(name, None)
    items[0]["quantity"] = "12.000000"
    path = f"/api/v1/amendments/{amended['pending_amendment']['id']}"
    response = client.patch(
        f"{path}/draft",
        headers=headers(fixtures, "buyer-operator", "buyer", amended["etag"]),
        json={"base_revision_id": amended["current_revision_id"], "changes": {"items": items}},
    )
    assert response.status_code == 200, response.text
    amended = response.json()
    response = client.post(
        f"{path}/offers",
        headers=headers(fixtures, "buyer-operator", "buyer", amended["etag"]),
        json={
            "revision_id": amended["current_revision_id"],
            "commercial_valid_until": (now() + timedelta(days=8)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    proposed = response.json()
    assert decision(env, proposed, "buyer").json()["accepted_revision_id"] == accepted_id
    result = decision(env, proposed).json()
    assert result["accepted_revision_id"] != accepted_id
    final = fetch(env, view["trade_id"])
    assert final["accepted_revision"]["facts"]["items"][0]["quantity"] == "12.000000"
    assert final["dispatch_readiness"] == "NOT_ASSESSED"
    history = client.get(
        f"/api/v1/trades/{view['trade_id']}/evidence-events", headers=headers(fixtures)
    ).json()["items"]
    assert {
        "TRADE_CREATED",
        "OFFER_PUBLISHED",
        "SELLER_ACCEPT",
        "BUYER_ACCEPT",
        "AGREEMENT_CONFIRMED",
        "AMENDMENT_CREATED",
        "AMENDMENT_ACCEPTED",
    } <= {row["action"] for row in history}
    assert all(
        row["actor_user_id"] and row["actor_organization_id"] and row["occurred_at"]
        for row in history
    )


@pytest.mark.parametrize("path", ["", "/evidence-events"])
def test_unrelated_organization_cannot_read(env, path):
    client, fixtures, *_ = env
    response = client.get(
        f"/api/v1/trades/{fixtures['trades']['OFFERED']}{path}",
        headers=headers(fixtures, "unrelated", "unrelated"),
    )
    assert response.status_code == 404


def test_role_switch_and_operator_do_not_grant_approval(env):
    client, fixtures, *_ = env
    view = fetch(env, fixtures["trades"]["OFFERED"])
    body = {
        "revision_id": view["active_offer"]["revision_id"],
        "terms_hash": view["active_offer"]["terms_hash"],
    }
    assert (
        client.post(
            f"/api/v1/offers/{view['active_offer']['id']}/confirmations",
            headers=headers(fixtures),
            json=body,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/offers/{view['active_offer']['id']}/confirmations",
            headers=headers(fixtures, "buyer-approver", "seller"),
            json=body,
        ).status_code
        == 403
    )
    assert client.get("/api/v1/trades?role=BUYER", headers=headers(fixtures)).json()["items"] == []
    assert decision(env, view, "buyer").json()["party_role"] == "BUYER"


def test_authentication_required_and_admin_has_no_implicit_approval(env):
    client, fixtures, *_ = env
    assert client.get("/api/v1/me").status_code == 401
    created = client.post(
        "/api/v1/organizations",
        headers={"X-Test-User": "unrelated", "Idempotency-Key": str(uuid4())},
        json={"legal_name": "New incomplete business"},
    )
    assert created.status_code == 201
    me = client.get("/api/v1/me", headers={"X-Test-User": "unrelated"}).json()
    member = next(
        item
        for item in me["memberships"]
        if item["organization_id"] == created.json()["organization_id"]
    )
    assert member["capabilities"] == ["ORG_ADMIN"]
    assert not any(
        item["permission_code"].startswith("order.confirm") for item in member["permissions"]
    )


def test_incomplete_draft_and_precise_publication_errors(env):
    view = create(env)
    response = publish(env, view)
    assert response.status_code == 422
    assert "delivery_requirements" in {
        item["path"] for item in response.json()["error"]["field_errors"]
    }
    assert fetch(env, view["trade_id"])["current_revision_id"] == view["current_revision_id"]


@pytest.mark.parametrize(
    "path,value,error_path",
    [
        (
            "commercial_terms.freight_payer",
            "SHARED",
            "commercial_terms.seller_freight_share_percent",
        ),
        ("commercial_terms.insurance_required", True, "commercial_terms.insurance_responsibility"),
        ("commercial_terms.payment_mode", "CREDIT", "commercial_terms.credit_days"),
        ("commercial_terms.payment_mode", "ADVANCE", "commercial_terms.advance_minor"),
        ("commercial_terms.payment_mode", "MILESTONE", "commercial_terms.milestone_schedule"),
        (
            "delivery_requirements.delivery_deadline_at",
            "2020-01-01T00:00:00Z",
            "delivery_requirements.delivery_deadline_at",
        ),
        (
            "delivery_requirements.receiving_window_end_local",
            "03:00",
            "delivery_requirements.receiving_window_crosses_midnight",
        ),
        ("items.0.temperature_controlled", True, "items.0.temperature_min_c"),
    ],
)
def test_publication_conditions(env, path, value, error_path):
    _, fixtures, *_ = env
    facts = demo_facts(fixtures["organizations"]["seller"], fixtures["organizations"]["buyer"])
    target = facts
    pieces = path.split(".")
    for key in pieces[:-1]:
        target = target[int(key)] if isinstance(target, list) else target[key]
    target[pieces[-1]] = value
    view = create(env, facts)
    response = publish(env, view)
    assert response.status_code == 422, response.text
    assert error_path in {item["path"] for item in response.json()["error"]["field_errors"]}


@pytest.mark.parametrize(
    "field_name", ["terms_hash", "agreement_status", "quoted_goods_total_minor"]
)
def test_client_derived_fields_rejected(env, field_name):
    client, fixtures, *_ = env
    response = client.post(
        "/api/v1/trades",
        headers=headers(fixtures),
        json={"initiated_by_role": "SELLER", "facts": {field_name: "invented"}},
    )
    assert response.status_code == 422


def test_exact_arithmetic_unknown_tax_and_discount_validation(env):
    _, fixtures, *_ = env
    facts = demo_facts(fixtures["organizations"]["seller"], fixtures["organizations"]["buyer"])
    view = create(env, facts)
    lines = view["current_candidate_revision"]["facts"]["items"]
    assert lines[0]["line_quoted_total_minor"] == "124500"
    assert lines[1]["line_quoted_total_minor"] == "9998"
    assert view["pricing_summary"]["complete_tax_estimate_minor"] is None
    assert view["pricing_summary"]["final_payable_minor"] is None
    facts["items"][0]["discount_minor"] = "9999999"
    assert price(facts)[2][0]["path"] == "items.0.discount_minor"


def test_idempotency_and_stale_autosave(env):
    client, fixtures, *_ = env
    key = str(uuid4())
    first, second = create(env, key=key), create(env, key=key)
    assert first == second
    changed = client.post(
        "/api/v1/trades",
        headers=headers(fixtures, key=key),
        json={"initiated_by_role": "SELLER", "facts": {"tax_terms": "Different"}},
    )
    assert (
        changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )
    path = f"/api/v1/trades/{first['trade_id']}/draft"
    payload = {
        "base_revision_id": first["current_revision_id"],
        "changes": {"tax_terms": "Saved once"},
    }
    assert (
        client.patch(path, headers=headers(fixtures, etag=first["etag"]), json=payload).status_code
        == 200
    )
    assert (
        client.patch(path, headers=headers(fixtures, etag=first["etag"]), json=payload).status_code
        == 412
    )
    assert (
        fetch(env, first["trade_id"])["current_candidate_revision"]["facts"]["tax_terms"]
        == "Saved once"
    )


def test_revisions_must_match_and_repeat_confirmation_is_not_duplicated(env):
    _, fixtures, sessions, _ = env
    offered = fetch(env, fixtures["trades"]["OFFERED"])
    assert decision(env, offered, hash_value="0" * 64).status_code == 409
    assert decision(env, offered, revision=str(uuid4())).status_code == 409
    first = decision(env, offered)
    assert first.status_code == 200, first.text
    second = decision(env, offered)
    assert second.status_code == 200
    assert first.json()["approval_id"] == second.json()["approval_id"]
    with sessions() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(Approval).where(Approval.offer_id == offered["active_offer"]["id"])
                    )
                )
            )
            == 1
        )


def test_withdraw_edit_requires_new_approvals(env):
    client, fixtures, *_ = env
    view = fetch(env, fixtures["trades"]["OFFERED"])
    assert decision(env, view).status_code == 200
    latest = fetch(env, view["trade_id"])
    path = f"/api/v1/trades/{view['trade_id']}/draft"
    assert client.patch(
        path,
        headers=headers(fixtures, etag=latest["etag"]),
        json={
            "base_revision_id": latest["current_revision_id"],
            "changes": {"tax_terms": "Changed"},
        },
    ).status_code in {403, 409}
    response = client.post(
        f"/api/v1/offers/{view['active_offer']['id']}/withdrawals",
        headers=headers(fixtures, etag=latest["etag"]),
        json={"reason": "Replace terms"},
    )
    assert response.status_code == 200, response.text
    assert decision(env, view, "buyer").status_code == 409
    replacement = publish(env, response.json())
    assert replacement.status_code == 200, replacement.text
    assert all(row["decision"] == "PENDING" for row in replacement.json()["approval_progress"])


def test_expired_offer_does_not_accept_new_decision(env):
    _, fixtures, sessions, _ = env
    view = fetch(env, fixtures["trades"]["OFFERED"])
    with sessions() as db:
        db.get(Offer, view["active_offer"]["id"]).expires_at = now() - timedelta(seconds=1)
        db.commit()
    response = decision(env, view)
    assert response.status_code == 409 and response.json()["error"]["code"] == "OFFER_EXPIRED"


@pytest.mark.parametrize("operation", ["rejections", "withdrawals"])
def test_rejected_or_withdrawn_amendment_preserves_accepted(env, operation):
    client, fixtures, *_ = env
    view = fetch(env, fixtures["trades"]["CONFIRMED"])
    base = view["accepted_revision"]["id"]
    response = client.post(
        f"/api/v1/trades/{view['trade_id']}/amendments",
        headers=headers(fixtures, etag=view["etag"]),
        json={"base_accepted_revision_id": base, "reason": "Proposed amendment"},
    )
    assert response.status_code == 200
    candidate = response.json()
    if operation == "rejections":
        offered = client.post(
            f"/api/v1/amendments/{candidate['pending_amendment']['id']}/offers",
            headers=headers(fixtures, etag=candidate["etag"]),
            json={
                "revision_id": candidate["current_revision_id"],
                "commercial_valid_until": (now() + timedelta(days=3)).isoformat(),
            },
        ).json()
        assert decision(env, offered, "buyer", reject=True).status_code == 200
    else:
        assert (
            client.post(
                f"/api/v1/amendments/{candidate['pending_amendment']['id']}/withdrawals",
                headers=headers(fixtures),
                json={"reason": "Keep existing agreement"},
            ).status_code
            == 200
        )
    assert fetch(env, view["trade_id"])["accepted_revision"]["id"] == base


def test_stale_amendment_and_second_proposal_are_rejected(env):
    client, fixtures, *_ = env
    view = fetch(env, fixtures["trades"]["CONFIRMED"])
    path = f"/api/v1/trades/{view['trade_id']}/amendments"
    assert (
        client.post(
            path,
            headers=headers(fixtures, etag=view["etag"]),
            json={"base_accepted_revision_id": str(uuid4()), "reason": "Stale"},
        ).status_code
        == 409
    )
    body = {"base_accepted_revision_id": view["accepted_revision"]["id"], "reason": "One proposal"}
    assert (
        client.post(path, headers=headers(fixtures, etag=view["etag"]), json=body).status_code
        == 200
    )
    latest = fetch(env, view["trade_id"])
    assert (
        client.post(
            path, headers=headers(fixtures, "buyer-operator", "buyer", latest["etag"]), json=body
        ).status_code
        == 409
    )


def test_profiles_do_not_rewrite_snapshots_and_history_is_immutable(env):
    client, fixtures, sessions, _ = env
    view = fetch(env, fixtures["trades"]["CONFIRMED"])
    org = fixtures["organizations"]["seller"]
    profile = client.get(f"/api/v1/organizations/{org}", headers=headers(fixtures)).json()
    assert (
        client.patch(
            f"/api/v1/organizations/{org}",
            headers=headers(fixtures, etag=profile["etag"]),
            json={"legal_name": "New legal name"},
        ).status_code
        == 200
    )
    assert (
        fetch(env, view["trade_id"])["accepted_revision"]["facts"]["bill_from"]["legal_name"]
        == "Demo Tamil Nadu Seller"
    )
    with sessions() as db:
        revision = db.get(Revision, view["accepted_revision"]["id"])
        revision.terms_hash = "0" * 64
        with pytest.raises(Exception, match="immutable"):
            db.commit()


def test_trade_scoped_expiring_grants_and_idempotent_replay_revocation(env):
    _, fixtures, sessions, _ = env
    view = fetch(env, fixtures["trades"]["OFFERED"])
    with sessions() as db:
        member = db.scalar(
            select(Membership).where(
                Membership.user_id == fixtures["users"]["buyer-approver"],
                Membership.organization_id == fixtures["organizations"]["buyer"],
            )
        )
        grant = db.scalar(
            select(Grant).where(
                Grant.membership_id == member.id,
                Grant.permission_code == "order.confirm.buyer",
            )
        )
        grant_id = grant.id
        grant.trade_id = fixtures["trades"]["CONFIRMED"]
        db.commit()
    assert decision(env, view, "buyer").status_code == 403
    with sessions() as db:
        grant = db.get(Grant, grant_id)
        grant.trade_id = view["trade_id"]
        grant.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert decision(env, view, "buyer").status_code == 403
    with sessions() as db:
        db.get(Grant, grant_id).expires_at = now() + timedelta(hours=1)
        db.commit()
    key = str(uuid4())
    assert decision(env, view, "buyer", key=key).status_code == 200
    with sessions() as db:
        db.get(Grant, grant_id).revoked_at = now()
        db.commit()
    assert decision(env, view, "buyer", key=key).status_code == 403


def test_nullable_terms_and_nested_incomplete_drafts_return_field_errors(env):
    client, fixtures, *_ = env
    view = create(
        env,
        {
            "commercial_terms": None,
            "items": [{"description": "Pending goods"}],
            "buyer_organization_id": fixtures["organizations"]["buyer"],
            "bill_to": {"billing_address": {"city": "Bengaluru"}},
        },
    )
    response = publish(env, view)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    paths = {item["path"] for item in response.json()["error"]["field_errors"]}
    assert "items.0.quantity" in paths
    assert "commercial_terms.freight_payer" in paths


def test_commercial_hash_normalizes_numbers_timezones_and_excludes_record_ids(env):
    client, fixtures, *_ = env
    facts = demo_facts(fixtures["organizations"]["seller"], fixtures["organizations"]["buyer"])
    equivalent = deepcopy(facts)
    equivalent["items"][0].update(
        quantity="10.0", unit_price_minor="12500", discount_minor="000500"
    )
    ist = timezone(timedelta(hours=5, minutes=30))
    for key in ("pickup_earliest_at", "pickup_latest_at", "delivery_deadline_at"):
        equivalent["delivery_requirements"][key] = (
            datetime.fromisoformat(facts["delivery_requirements"][key].replace("Z", "+00:00"))
            .astimezone(ist)
            .isoformat()
        )
    offered = []
    for value in (facts, equivalent):
        view = create(env, value)
        response = client.post(
            f"/api/v1/trades/{view['trade_id']}/offers",
            headers=headers(fixtures, etag=view["etag"]),
            json={
                "revision_id": view["current_revision_id"],
                "commercial_valid_until": facts["commercial_terms"]["commercial_valid_until"],
            },
        )
        assert response.status_code == 200, response.text
        offered.append(response.json()["active_offer"])
    assert offered[0]["id"] != offered[1]["id"]
    assert offered[0]["revision_id"] != offered[1]["revision_id"]
    assert offered[0]["terms_hash"] == offered[1]["terms_hash"]


def test_partner_search_privacy_and_registration_ownership(env):
    client, fixtures, *_ = env
    seller, buyer = fixtures["organizations"]["seller"], fixtures["organizations"]["buyer"]
    declaration = {
        "gstin": "33ABCDE1234F1Z9",
        "state_code": "33",
        "declared_taxpayer_scheme": "REGULAR",
        "declared_establishment_kind": "NORMAL",
    }
    # Build the checksum rather than asserting authority over a real business.
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    body = declaration["gstin"][:14]
    total = sum(
        (alphabet.index(char) * (1 if index % 2 == 0 else 2)) // 36
        + (alphabet.index(char) * (1 if index % 2 == 0 else 2)) % 36
        for index, char in enumerate(body)
    )
    declaration["gstin"] = body + alphabet[(36 - total % 36) % 36]
    registration = client.post(
        f"/api/v1/organizations/{seller}/registrations", headers=headers(fixtures), json=declaration
    )
    assert registration.status_code == 201, registration.text
    assert registration.json()["verification_status"] == "FORMAT_VALIDATED"
    assert (
        client.post(
            f"/api/v1/organizations/{buyer}/registrations",
            headers=headers(fixtures, "buyer-operator", "buyer"),
            json=declaration,
        ).status_code
        == 409
    )
    location = {
        "registration_id": registration.json()["id"],
        "label": "Forbidden",
        "location_type": "OFFICE",
        "address": demo_address(),
        "visibility": "PRIVATE",
    }
    assert (
        client.post(
            f"/api/v1/organizations/{buyer}/locations",
            headers=headers(fixtures, "buyer-operator", "buyer"),
            json=location,
        ).status_code
        == 422
    )
    location["registration_id"] = None
    assert (
        client.post(
            f"/api/v1/organizations/{seller}/locations", headers=headers(fixtures), json=location
        ).status_code
        == 201
    )
    partner = client.get(
        "/api/v1/trading-partners?q=Tamil", headers=headers(fixtures, "buyer-operator", "buyer")
    ).json()["items"][0]
    assert (
        "email" not in partner and "registered_address" not in partner and "members" not in partner
    )
    assert partner["trading_locations"] == []
    assert (
        client.get(
            f"/api/v1/organizations/{seller}", headers=headers(fixtures, "buyer-operator", "buyer")
        ).status_code
        == 403
    )
    with pytest.raises(ValueError):
        gstin_format(declaration["gstin"][:-1] + ("0" if declaration["gstin"][-1] != "0" else "1"))


def test_same_org_can_buy_and_sell_with_explicit_grants(env):
    client, fixtures, *_ = env
    seller = fixtures["organizations"]["seller"]
    response = client.post(
        f"/api/v1/organizations/{seller}/members",
        headers=headers(fixtures),
        json={
            "user_id": fixtures["users"]["seller-operator"],
            "capabilities": ["ORG_ADMIN", "SELLER_OPERATOR", "BUYER_OPERATOR"],
        },
    )
    assert response.status_code == 200
    created = client.post(
        "/api/v1/trades",
        headers=headers(fixtures),
        json={"initiated_by_role": "BUYER", "facts": {}},
    )
    assert created.status_code == 201
    assert created.json()["trade_id"] in {
        row["trade_id"]
        for row in client.get("/api/v1/trades?role=BUYER", headers=headers(fixtures)).json()[
            "items"
        ]
    }
    assert fixtures["trades"]["DRAFT"] in {
        row["trade_id"]
        for row in client.get("/api/v1/trades?role=SELLER", headers=headers(fixtures)).json()[
            "items"
        ]
    }


@pytest.mark.parametrize("race", ["confirm", "withdraw", "amend"])
def test_postgresql_transaction_races(env, race):
    client, fixtures, sessions, postgres = env
    if not postgres:
        pytest.skip("Run with TRADE_TEST_DATABASE_URL for PostgreSQL row-lock races")
    view = fetch(env, fixtures["trades"]["CONFIRMED" if race == "amend" else "OFFERED"])
    if race == "withdraw":
        assert decision(env, view, "seller").status_code == 200
        view = fetch(env, view["trade_id"])

    def competing(side):
        if race == "confirm" or (race == "withdraw" and side == "buyer"):
            return decision(env, view, side)
        if race == "withdraw":
            return client.post(
                f"/api/v1/offers/{view['active_offer']['id']}/withdrawals",
                headers=headers(fixtures, etag=view["etag"]),
                json={"reason": "Race withdrawal"},
            )
        return client.post(
            f"/api/v1/trades/{view['trade_id']}/amendments",
            headers=headers(fixtures, f"{side}-operator", side, view["etag"]),
            json={
                "base_accepted_revision_id": view["accepted_revision"]["id"],
                "reason": "Parallel proposal",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(competing, ["seller", "buyer"]))
    assert all(response.status_code in {200, 409, 412} for response in results), [
        response.text for response in results
    ]
    final = fetch(env, view["trade_id"])
    if race == "confirm":
        assert [response.status_code for response in results] == [200, 200]
        assert final["agreement_status"] == "CONFIRMED"
    elif race == "withdraw":
        with sessions() as db:
            if db.get(Offer, view["active_offer"]["id"]).status == "WITHDRAWN":
                assert final["accepted_revision"] is None
    else:
        assert sum(response.status_code == 200 for response in results) == 1
        assert final["pending_amendment"] is not None
