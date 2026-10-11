from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from tradetwin_security import ProfileMiddleware, migrate_ownership

from app.config import settings
from app.database import Base, engine
from app.error_handlers import configure_error_handling
from app.jobs import ComplianceJobStore
from app.regulatory_sources import router as regulatory_sources_router
from app.routers import assessments, consistency, operations, optimizer, regulations, reports
from app.state_relations import router as state_relations_router

SERVICE_NAME = "compliance-service"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    migrate_ownership(engine, Base.metadata)
    Base.metadata.create_all(bind=engine)
    app.state.job_store = ComplianceJobStore()
    try:
        yield
    finally:
        app.state.job_store.close()


app = FastAPI(
    title="TradeTwin Compliance Service",
    version="0.7.0",
    description=(
        "Deterministic compliance, evidence-backed reports, route optimization, "
        "regulation impact analysis, demo auth/RBAC, and audit logs."
    ),
    openapi_tags=[
        {"name": "health", "description": "Service readiness checks."},
        {"name": "auth", "description": "Demo authentication context."},
        {"name": "compliance", "description": "Rule-based assessments."},
        {"name": "consistency", "description": "Conflict checks and questions."},
        {"name": "optimizer", "description": "Deterministic route comparison."},
        {"name": "regulations", "description": "Regulation version management."},
        {"name": "reports", "description": "HTML and PDF compliance reports."},
        {"name": "audit", "description": "Immutable-style audit trail reads."},
        {"name": "demo", "description": "Seeded project evaluation scenarios."},
    ],
    lifespan=lifespan,
)


app.add_middleware(ProfileMiddleware)
app.include_router(regulatory_sources_router)
app.include_router(state_relations_router)
for router_module in (assessments, optimizer, regulations, reports, operations, consistency):
    app.include_router(router_module.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
configure_error_handling(app)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready", tags=["health"])
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        app.state.job_store.check_ready()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Compliance dependencies unavailable") from exc
    return {"status": "ok", "service": SERVICE_NAME}
