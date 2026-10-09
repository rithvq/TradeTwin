# ruff: noqa: E402
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from authlib.integrations.starlette_client import OAuth
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]
from app import auth, main


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(auth, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(main, "engine", engine)
    with TestClient(main.app) as client:
        yield client
    engine.dispose()


def test_callback_creates_reusable_profile_and_revocable_private_session(client, monkeypatch):
    provider = AsyncMock()
    provider.authorize_access_token.return_value = {
        "userinfo": {
            "sub": "subject-1",
            "iss": "https://identity.test",
            "name": "Alice",
            "email": "alice@test.invalid",
        }
    }
    monkeypatch.setattr(auth, "configured", True)
    monkeypatch.setattr(auth.oauth, "create_client", lambda _name: provider)
    response = client.get("/auth/callback", follow_redirects=False)
    assert response.status_code == 303
    cookie = response.headers.get_list("set-cookie")[0]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    user = client.get("/auth/session").json()
    first_token = client.cookies.get(auth.COOKIE)
    with auth.SessionLocal() as db:
        stored = db.scalar(select(auth.LoginSession))
        assert stored.token_hash == auth.token_hash(first_token)
        assert stored.token_hash != first_token
    client.get("/auth/callback", follow_redirects=False)
    assert client.get("/auth/session").json()["id"] == user["id"]
    assert (
        client.get("/auth/session", headers={"Authorization": f"Bearer {first_token}"}).status_code
        == 401
    )
    assert (
        client.post("/auth/logout", headers={"Origin": "https://attacker.invalid"}).status_code
        == 403
    )
    assert client.post("/auth/logout", headers={"Origin": auth.public_url}).status_code == 200
    assert client.get("/auth/session").status_code == 401


def test_expired_session_and_invalid_callback_are_rejected(client, monkeypatch):
    with auth.SessionLocal() as db:
        profile = auth.Profile(
            issuer="https://identity.test", subject="expired", name="A", email="a@test.invalid"
        )
        db.add(profile)
        db.flush()
        db.add(
            auth.LoginSession(
                token_hash=auth.token_hash("expired"),
                profile_id=profile.id,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        db.commit()
    assert (
        client.get("/auth/session", headers={"Authorization": "Bearer expired"}).status_code == 401
    )
    actual_oauth = OAuth()
    actual_oauth.register(
        name="identity",
        client_id="test",
        client_secret="test",
        authorize_url="https://identity.test/authorize",
        access_token_url="https://identity.test/token",
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )
    monkeypatch.setattr(auth, "oauth", actual_oauth)
    monkeypatch.setattr(auth, "configured", True)
    response = client.get("/auth/callback?code=forged&state=forged", follow_redirects=False)
    assert response.status_code == 303 and "error=signin" in response.headers["location"]
    assert client.cookies.get(auth.COOKIE) is None
    from urllib.parse import parse_qs, urlparse

    login = client.get("/auth/login", follow_redirects=False)
    params = parse_qs(urlparse(login.headers["location"]).query)
    assert params["state"] and params["nonce"] and params["code_challenge"]
    assert params["code_challenge_method"] == ["S256"]


def test_missing_configuration_has_no_demo_login_bypass(client, monkeypatch):
    monkeypatch.setattr(auth, "configured", False)
    assert client.get("/auth/providers").json()["configured"] is False
    assert (
        "error=configuration"
        in client.get("/auth/login", follow_redirects=False).headers["location"]
    )
    assert (
        client.get("/auth/session", headers={"Authorization": "Bearer demo-admin"}).status_code
        == 401
    )
