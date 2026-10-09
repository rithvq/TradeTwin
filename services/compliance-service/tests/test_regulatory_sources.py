# ruff: noqa: E402, I001
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app import regulatory_sources as sources
from app.auth import Principal
from app.database import Base
from app.models import RegulatorySourceSnapshot, RegulationVersion
from app.regulations import (
    demo_domestic_rule,
    load_rules_with_published,
    publish_regulation_version,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_source_url_guardrails(monkeypatch):
    for url in [
        "http://gstcouncil.gov.in/",
        "https://localhost/",
        "https://evil.com/",
        "https://gstcouncil.gov.in.evil.com/",
        "https://user@gstcouncil.gov.in/",
    ]:
        with pytest.raises(ValueError):
            sources.validate_url(url)
    monkeypatch.setattr(
        sources.socket, "getaddrinfo", lambda *a, **kw: [(0, 0, 0, "", ("127.0.0.1", 443))]
    )
    with pytest.raises(ValueError):
        sources.validate_url("https://gstcouncil.gov.in/")


def test_draft_review_publication_and_changed_source(db, monkeypatch):
    text = "This is a test fixture and not an actual government regulation. " * 3
    monkeypatch.setattr(sources, "retrieve", lambda url: (text, "a" * 64))
    principal = Principal("test-admin", "admin")
    snapshot = sources.fetch_source(
        sources.SourceRequest(url=sources.SOURCES[0]["url"]), db, principal
    )
    rule = demo_domestic_rule().model_copy(update={"source_url": snapshot["url"]})
    draft = sources.DraftRequest(rule=rule, quote=text.strip())
    result = sources.draft_rule(snapshot["id"], draft, db, principal)
    with pytest.raises(HTTPException) as error:
        publish_regulation_version(db, result["regulation_id"])
    assert error.value.status_code == 409
    assert db.get(RegulationVersion, result["regulation_id"]).status == "DRAFT"
    sources.approve(
        result["review_id"],
        sources.ReviewRequest(note="Reviewed test fixture scope and effective dates"),
        db,
        principal,
    )
    publish_regulation_version(db, result["regulation_id"])
    assert db.get(RegulationVersion, result["regulation_id"]).status == "PUBLISHED"
    monkeypatch.setattr(sources.settings, "regulation_catalog_mode", "reviewed")
    assert len(load_rules_with_published(db)) == 1
    monkeypatch.setattr(sources, "retrieve", lambda url: (text + "amended", "b" * 64))
    sources.fetch_source(sources.SourceRequest(url=snapshot["url"]), db, principal)
    with pytest.raises(HTTPException):
        sources.ensure_source_review(db, result["regulation_id"])


def test_fabricated_quote_and_empty_catalog(db, monkeypatch):
    row = RegulatorySourceSnapshot(
        url=sources.SOURCES[0]["url"], content_hash="a" * 64, payload={"text": "source text"}
    )
    db.add(row)
    db.commit()
    draft = sources.DraftRequest(
        rule=demo_domestic_rule(), quote="A fabricated legal obligation that is not in the source."
    )
    with pytest.raises(HTTPException):
        sources.validate_grounding(row, draft)
    monkeypatch.setattr(sources.settings, "regulation_catalog_mode", "reviewed")
    assert load_rules_with_published(db) == []
    monkeypatch.setattr(sources.settings, "regulation_llm_api_key", None)
    with pytest.raises(HTTPException) as error:
        sources.suggest(row.id, db, Principal("test", "admin"))
    assert error.value.status_code == 503


def test_invalid_dynamic_condition_rejected():
    for value in ["50000", -1, float("nan"), True]:
        payload = demo_domestic_rule().model_dump()
        payload["conditions"]["consignment_value_above"] = value
        with pytest.raises(ValueError):
            sources.ComplianceRule.model_validate(payload)
