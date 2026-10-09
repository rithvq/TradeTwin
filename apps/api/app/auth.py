import hashlib
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])
public_url = os.getenv("APP_PUBLIC_URL", "http://localhost:3000").rstrip("/")
cookie_secure = public_url.startswith("https://")
COOKIE = "tt_session"
session_secret = os.getenv("OAUTH_STATE_SECRET") or secrets.token_urlsafe(48)
database_url = settings.database_url or "sqlite+pysqlite:///./auth.db"
kwargs = {"connect_args": {"check_same_thread": False}} if database_url.startswith("sqlite") else {}
if ":memory:" in database_url:
    kwargs["poolclass"] = StaticPool
engine = create_engine(database_url, **kwargs)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "auth_profiles"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_profile_identity"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class LoginSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("auth_profiles.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


oauth = OAuth()
provider_name = os.getenv("OAUTH_PROVIDER_NAME", "Google")
client_id = os.getenv("OAUTH_CLIENT_ID", "")
client_secret = os.getenv("OAUTH_CLIENT_SECRET", "")
issuer_metadata = os.getenv(
    "OAUTH_DISCOVERY_URL",
    "https://accounts.google.com/.well-known/openid-configuration",
)
configured = bool(client_id and client_secret and len(os.getenv("OAUTH_STATE_SECRET", "")) >= 32)
if configured:
    oauth.register(
        name="identity",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=issuer_metadata,
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )


def profile_payload(profile):
    return {"id": profile.id, "name": profile.name, "email": profile.email, "role": "admin"}


def session_token(request):
    authorization = request.headers.get("authorization", "")
    return (
        authorization[7:]
        if authorization.startswith("Bearer ")
        else request.cookies.get(COOKIE, "")
    )


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@router.get("/providers")
def providers():
    return {"provider": provider_name, "configured": configured}


@router.get("/login")
async def login(request: Request):
    if not configured:
        return RedirectResponse(f"{public_url}/login?error=configuration", status_code=303)
    request.session.clear()
    client = oauth.create_client("identity")
    return await client.authorize_redirect(
        request,
        f"{public_url}/api/auth/callback",
        prompt="select_account",
    )


@router.get("/callback")
async def callback(request: Request):
    if not configured:
        return RedirectResponse(f"{public_url}/login?error=configuration", status_code=303)
    try:
        client = oauth.create_client("identity")
        token = await client.authorize_access_token(request)
        # Authlib validates the signature, issuer, audience, expiry, nonce and OAuth state.
        claims = token["userinfo"]
        if not claims.get("sub") or not claims.get("iss"):
            raise ValueError("Missing identity claims")
        with SessionLocal() as db:
            profile = db.scalar(
                select(Profile).where(
                    Profile.issuer == claims["iss"],
                    Profile.subject == claims["sub"],
                )
            )
            if profile is None:
                profile = Profile(issuer=claims["iss"], subject=claims["sub"])
                db.add(profile)
            profile.name = str(claims.get("name") or "TradeTwin member")[:255]
            profile.email = str(claims.get("email") or "")[:320]
            db.flush()
            raw_token = secrets.token_urlsafe(48)
            previous = db.get(LoginSession, token_hash(session_token(request)))
            if previous:
                db.delete(previous)
            db.add(
                LoginSession(
                    token_hash=token_hash(raw_token),
                    profile_id=profile.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=12),
                )
            )
            db.commit()
        request.session.clear()
        response = RedirectResponse(f"{public_url}/dashboard", status_code=303)
        response.set_cookie(
            COOKIE,
            raw_token,
            max_age=43200,
            httponly=True,
            secure=cookie_secure,
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception:
        request.session.clear()
        return RedirectResponse(f"{public_url}/login?error=signin", status_code=303)


@router.get("/session")
def current_session(request: Request):
    token = session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required")
    with SessionLocal() as db:
        session = db.get(LoginSession, token_hash(token))
        if session is None:
            raise HTTPException(status_code=401, detail="Session expired")
        expires = (
            session.expires_at.replace(tzinfo=UTC)
            if session.expires_at.tzinfo is None
            else session.expires_at
        )
        if expires <= datetime.now(UTC):
            db.delete(session)
            db.commit()
            raise HTTPException(status_code=401, detail="Session expired")
        profile = db.get(Profile, session.profile_id)
        if profile is None:
            raise HTTPException(status_code=401, detail="Profile unavailable")
        return JSONResponse(profile_payload(profile), headers={"Cache-Control": "no-store"})


@router.post("/logout")
def logout(request: Request):
    if request.headers.get("origin") != public_url:
        raise HTTPException(status_code=403, detail="Invalid request origin")
    with SessionLocal() as db:
        session = db.get(LoginSession, token_hash(session_token(request)))
        if session:
            db.delete(session)
            db.commit()
    request.session.clear()
    response = JSONResponse({"signed_out": True}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE, path="/", secure=cookie_secure, httponly=True, samesite="lax")
    return response
