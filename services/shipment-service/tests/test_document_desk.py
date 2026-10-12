import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from tradetwin_security import identity

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module in list(sys.modules):
    if module == "app" or module.startswith("app."):
        del sys.modules[module]

from app.database import get_db  # noqa: E402
from app.document_desk import jobs, schemas, worker  # noqa: E402
from app.document_desk.ledger import flatten  # noqa: E402
from app.document_desk.models import (  # noqa: E402
    Assessment,
    Asset,
    Extraction,
    FactRevision,
    Job,
    LineMapping,
    Observation,
    Version,
)
from app.operations.cli import Demo  # noqa: E402
from app.operations.demo import ROLES, seed_demo  # noqa: E402
from app.operations.models import (  # noqa: E402
    Attachment,
    Consignment,
    Payment,
    Receipt,
    Schedule,
)
from app.trades.errors import TradeError, install_handlers  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import Grant, Membership, Revision, Trade, now, uid  # noqa: E402
from app.trades.reference import ROLE_PERMISSIONS  # noqa: E402
from app.trades.router import router  # noqa: E402


@pytest.fixture()
def flow(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    engine = create_engine(
        url or f"sqlite:///{tmp_path / 'documents.db'}",
        connect_args={} if url else {"check_same_thread": False},
    )
    if not url:

        @event.listens_for(engine, "connect")
        def enforce_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys = ON")

    schema = f"documents_test_{uuid4().hex}" if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    migrate(engine)
    migrate(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        fixture = seed_demo(db, namespace="phase3-test")
        for name, capability in (
            ("seller-operations", "SELLER_DOCUMENT_REVIEWER"),
            ("buyer-receiver", "BUYER_DOCUMENT_REVIEWER"),
        ):
            member = db.scalar(
                select(Membership).where(Membership.user_id == fixture["users"][name])
            )
            for permission in ROLE_PERMISSIONS[capability]:
                db.add(
                    Grant(
                        membership_id=member.id, capability=capability, permission_code=permission
                    )
                )
        db.commit()
    app = FastAPI()
    app.include_router(router)
    install_handlers(app)

    def dependency():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = dependency

    @app.middleware("http")
    async def fixture_identity(request, call_next):
        role = request.headers.get("X-Test-User")
        token = identity.set({"id": fixture["subjects"][role]} if role else None)
        try:
            return await call_next(request)
        finally:
            identity.reset(token)

    with TestClient(app) as client:
        yield Flow(client, fixture, sessions, bool(url))
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


class Flow:
    def __init__(self, client, fx, sessions, postgres):
        self.client, self.fx, self.sessions, self.postgres = client, fx, sessions, postgres

    def request(self, method, path, body=None, role="seller-operations", etag=None, key=None):
        headers = {
            "X-Test-User": role,
            "X-Organization-Id": self.fx["organizations"][ROLES[role][0]],
            "Idempotency-Key": key or uid(),
        }
        if etag:
            headers["If-Match"] = etag
        return self.client.request(method, f"/api/v1{path}", json=body, headers=headers)

    def get(self, path, role="seller-operations"):
        response = self.request("GET", path, role=role)
        assert response.status_code == 200, response.text
        return response.json()

    def attachment(self, clean="CLEAN", purpose="OTHER", role="seller-operations", cn=None):
        with self.sessions() as db:
            row = Attachment(
                id=uid(),
                trade_id=self.fx["trade_id"],
                consignment_id=cn,
                purpose=purpose,
                original_name="invoice.pdf",
                content_type="application/pdf",
                size_bytes=123,
                object_key="test-only.enc",
                sha256=hashlib.sha256(uid().encode()).hexdigest(),
                security_state=clean,
                uploaded_by_organization_id=self.fx["organizations"][ROLES[role][0]],
                created_by=self.fx["users"][role],
                finalised_at=now(),
            )
            db.add(row)
            db.commit()
            return row.id

    def document(
        self,
        kind="TAX_INVOICE",
        clean="CLEAN",
        role="seller-operations",
        visibility="TRADE_PARTIES",
        cn=None,
    ):
        attachment = self.attachment(
            clean, "PAYMENT" if kind == "PAYMENT_EVIDENCE" else "OTHER", role, cn
        )
        response = self.request(
            "POST",
            f"/trades/{self.fx['trade_id']}/documents",
            {
                "document_type": kind,
                "label": "Test document",
                "trade_id": self.fx["trade_id"],
                "primary_attachment_id": attachment,
                "visibility": visibility,
                "initial_consignment_id": cn,
            },
            role,
        )
        return response

    def extract(self, doc, reprocess=False, canonical=None):
        response = self.request(
            "POST",
            f"/document-versions/{doc['current_version_id']}/processing-jobs",
            {"stage": "EXTRACT", "strategy": "AUTO", "reprocess": reprocess},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]
        with self.sessions() as db:
            lease = jobs.claim(db, "unit-test-worker", job_id)
        if not lease:
            return self.get(f"/documents/{doc['id']}")
        self.finish(lease, canonical)
        return self.get(f"/documents/{doc['id']}")

    def finish(self, lease, canonical=None):
        with self.sessions() as db:
            job = db.get(Job, lease[0])
            version = db.get(Version, job.document_version_id)
            asset = db.scalar(
                select(Asset).where(
                    Asset.document_version_id == version.id, Asset.role == "PRIMARY"
                )
            )
            line_id, image_id = uid(), uid()
            canonical = canonical or {
                "header": {
                    "document_number": "INV-000001",
                    "issue_date": "2026-10-12",
                    "currency": "INR",
                    "document_profile": "SIMPLE_DECLARED_TOTALS",
                },
                "parties": {
                    "supplier": {
                        "legal_name": "Operational demo phase3-test seller",
                        "gstin": "33ABCDE1234F1Z5",
                    }
                },
                "lines": [
                    {
                        "document_line_ref": line_id,
                        "description": "Demo electric motors",
                        "quantity": "100",
                        "uqc": "NOS",
                        "unit_price_minor": "10000",
                        "taxable_value_minor": "1000000",
                        "line_discount_minor": "0",
                    }
                ],
                "totals": {
                    "taxable_subtotal_minor": "1000000",
                    "cgst_total_minor": "0",
                    "sgst_total_minor": "0",
                    "igst_total_minor": "180000",
                    "cess_total_minor": "0",
                    "state_cess_total_minor": "0",
                    "other_charges_minor": "0",
                    "round_off_minor": "0",
                    "grand_total_minor": "1180000",
                    "discount_treatment": "INCLUDED_IN_TAXABLE_SUBTOTAL",
                },
            }
            canonical = schemas.CanonicalDocument.model_validate(canonical).model_dump(mode="json")
            observations = [
                {
                    "field_path": "lines.*." + path.split(".")[-1]
                    if path.startswith("lines.")
                    else path,
                    "row_key": "0" if path.startswith("lines.") else None,
                    "raw_text": str(value),
                    "normalised_value_json": value,
                    "value_type": "STRING",
                    "extraction_method": "NATIVE_TEXT",
                    "provider_confidence": None,
                    "validation_status": "PARSED",
                    "normalisation_warnings_json": [],
                    "source_locator_json": {
                        "source_attachment_id": asset.attachment_id,
                        "page_number": 1,
                        "coordinate_space": "RENDERED_PAGE_TOP_LEFT",
                        "bounding_box": {"x0": 0.1, "x1": 0.9, "y0": 0.1, "y1": 0.2},
                    },
                }
                for path, value in flatten(canonical).items()
            ]
            output = {
                "canonical_document": canonical,
                "observations": observations,
                "engine_kind": "RULES",
                "engine_name": "Deterministic unit fixture",
                "engine_version": "1",
                "status": "SUCCEEDED",
                "artifacts": [
                    {
                        "id": image_id,
                        "document_version_id": version.id,
                        "job_attempt_id": lease[1],
                        "source_attachment_id": asset.attachment_id,
                        "artifact_type": "PAGE_IMAGE",
                        "object_key": f"derived/{version.id}/{lease[1]}/{image_id}.enc",
                        "content_type": "image/png",
                        "size_bytes": 1,
                        "sha256": "a" * 64,
                        "transformation_metadata_json": {},
                    }
                ],
                "pages": [
                    {
                        "page_number": 1,
                        "page_image_artifact_id": image_id,
                        "width_px": 100,
                        "height_px": 100,
                        "transformation_json": {},
                    }
                ],
            }
            jobs.finish_extraction(db, lease, output)

    def reviewed(self, doc):
        fact = self.get(f"/document-fact-revisions/{doc['latest_draft_fact_revision_id']}")
        observations = self.get(
            f"/document-extraction-runs/{fact['extraction_run_id']}/observations"
        )["items"]
        decisions = []
        for path, value in flatten(fact["canonical_document_json"]).items():
            field = "lines.*." + path.split(".")[-1] if path.startswith("lines.") else path
            obs = next(o for o in observations if o["field_path"] == field)
            decisions.append(
                {
                    "field_path": path,
                    "observation_id": obs["id"],
                    "effective_value": value,
                    "decision": "CONFIRMED",
                    "provenance": "EXTRACTION_REVIEW",
                }
            )
        response = self.request(
            "POST",
            f"/document-versions/{doc['current_version_id']}/fact-revisions",
            {
                "base_fact_revision_id": fact["id"],
                "extraction_run_id": fact["extraction_run_id"],
                "canonical_document": fact["canonical_document_json"],
                "field_decisions": decisions,
            },
            etag=doc["etag"],
        )
        assert response.status_code == 201, response.text
        saved = response.json()
        response = self.request(
            "POST",
            f"/document-fact-revisions/{saved['id']}/submissions",
            {"content_hash": saved["content_hash"]},
            etag=saved["etag"],
        )
        assert response.status_code == 200, response.text
        return self.get(f"/documents/{doc['id']}")

    def mapped(self, doc, quantities=("40", "60")):
        demo = Demo(self.sessions, self.fx)
        consignments = [demo.allocate("40"), demo.allocate("60")]
        fact = self.get(f"/document-fact-revisions/{doc['effective_fact_revision_id']}")
        with self.sessions() as db:
            trade = db.get(Trade, self.fx["trade_id"])
            revision_id = trade.accepted_revision_id
        body = {
            "fact_revision_id": fact["id"],
            "accepted_trade_revision_id": revision_id,
            "base_mapping_revision_id": None,
            "mappings": [
                {
                    "document_line_ref": fact["canonical_document_json"]["lines"][0][
                        "document_line_ref"
                    ],
                    "trade_line_ref": cn["items"][0]["line_ref"],
                    "target_kind": "CONSIGNMENT_ITEM",
                    "consignment_item_id": cn["items"][0]["id"],
                    "mapped_quantity": quantity,
                    "uqc": "NOS",
                }
                for cn, quantity in zip(consignments, quantities, strict=True)
            ],
        }
        return self.request(
            "POST", f"/documents/{doc['id']}/mapping-revisions", body, etag=doc["etag"]
        ), consignments


def prepared(flow):
    response = flow.document()
    assert response.status_code == 201, response.text
    return flow.reviewed(flow.extract(response.json()))


def test_review_saves_parent_before_decisions_with_foreign_keys_enforced(flow):
    if not flow.postgres:
        with flow.sessions() as db:
            assert db.scalar(text("PRAGMA foreign_keys")) == 1
    doc = prepared(flow)
    fact = flow.get(f"/document-fact-revisions/{doc['effective_fact_revision_id']}")
    assert len(fact["field_decisions"]) == len(flatten(fact["canonical_document_json"]))


def test_real_revision_ledgers_mapping_40_60_totals_once_no_business_mutation(flow):
    with flow.sessions() as db:
        trade = db.get(Trade, flow.fx["trade_id"])
        revision_id, accepted = (
            trade.accepted_revision_id,
            db.get(Revision, trade.accepted_revision_id).terms_hash,
        )
    doc = prepared(flow)
    response, consignments = flow.mapped(doc)
    assert response.status_code == 201, response.text
    assert [m["mapped_quantity"] for m in response.json()["mappings"]] == ["40", "60"]
    fact = flow.get(f"/document-fact-revisions/{doc['effective_fact_revision_id']}")
    assert fact["canonical_document_json"]["totals"]["grand_total_minor"] == "1180000"
    with flow.sessions() as db:
        trade = db.get(Trade, flow.fx["trade_id"])
        assert trade.accepted_revision_id == revision_id
        assert db.get(Revision, revision_id).terms_hash == accepted
        assert db.scalar(select(func.count(Payment.id))) == 0
        assert db.scalar(select(func.count(Receipt.id))) == 0
        assert db.scalar(select(func.count(Schedule.id))) == 0
        assert all(
            db.get(Consignment, c["id"]).movement_status == "NOT_STARTED" for c in consignments
        )


@pytest.mark.parametrize(
    "quantities,code",
    [
        (("40", "70"), "DOCUMENT_MAPPING_QUANTITY_EXCEEDED"),
        (("41", "59"), "CONSIGNMENT_MAPPING_QUANTITY_EXCEEDED"),
    ],
)
def test_mapping_caps_are_transactional(flow, quantities, code):
    response, _ = flow.mapped(prepared(flow), quantities)
    assert response.status_code == 409 and response.json()["error"]["code"] == code
    with flow.sessions() as db:
        assert db.scalar(select(func.count(LineMapping.id))) == 0


@pytest.mark.parametrize("state", ["QUARANTINED", "REJECTED", "UPLOADING"])
def test_nonclean_registration_fails(flow, state):
    response = flow.document(clean=state)
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "ATTACHMENT_NOT_CLEAN"
    )


@pytest.mark.parametrize(
    "forged",
    [
        "execution_mode",
        "verified",
        "authentic",
        "authority_verified",
        "dispatch_ready",
        "provider_outcome",
        "signature_valid",
        "reviewed_by",
    ],
)
def test_client_cannot_assert_trusted_states(flow, forged):
    attachment = flow.attachment()
    response = flow.request(
        "POST",
        f"/trades/{flow.fx['trade_id']}/documents",
        {
            "document_type": "OTHER",
            "label": "Forged",
            "trade_id": flow.fx["trade_id"],
            "primary_attachment_id": attachment,
            forged: True,
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("suffix", ["", "/mappings", "/mapping-suggestions"])
def test_unrelated_and_carrier_cannot_read_invoice_routes(flow, suffix):
    doc = prepared(flow)
    for role in ("unrelated", "carrier-dispatcher", "driver-one"):
        response = flow.request("GET", f"/documents/{doc['id']}{suffix}", role=role)
        assert response.status_code in {403, 404}


def test_derived_endpoint_permission_checks_and_finance_type_restriction(flow):
    doc = prepared(flow)
    fact = flow.get(f"/document-fact-revisions/{doc['effective_fact_revision_id']}")
    for path in (
        f"/document-versions/{doc['current_version_id']}/pages",
        f"/document-versions/{doc['current_version_id']}/evidence-manifest",
        f"/document-extraction-runs/{fact['extraction_run_id']}/observations",
        f"/document-fact-revisions/{fact['id']}",
    ):
        assert flow.request("GET", path, role="carrier-dispatcher").status_code in {403, 404}
    assert flow.document(kind="PAYMENT_EVIDENCE").status_code == 403
    assert flow.document(kind="PAYMENT_EVIDENCE", role="seller-finance").status_code == 201


def test_job_deduplication_reprocessing_and_human_snapshot_preservation(flow):
    doc = prepared(flow)
    head = doc["effective_fact_revision_id"]
    doc = flow.extract(doc, reprocess=True)
    assert doc["effective_fact_revision_id"] == head
    assert doc["latest_draft_fact_revision_id"] == head
    with flow.sessions() as db:
        assert db.scalar(select(func.count(Extraction.id))) == 2
    doc = flow.extract(doc)
    with flow.sessions() as db:
        assert db.scalar(select(func.count(Extraction.id))) == 2


def test_cancellation_and_lease_loss_cannot_publish(flow):
    doc = flow.document().json()
    response = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/processing-jobs",
        {"stage": "EXTRACT"},
    )
    job_id = response.json()["job_id"]
    with flow.sessions() as db:
        lease = jobs.claim(db, "cancel-test", job_id)
    job = flow.get(f"/document-processing-jobs/{job_id}")
    response = flow.request(
        "POST",
        f"/document-processing-jobs/{job_id}/cancellations",
        {"reason": "Cancelled test"},
        etag=job["etag"],
    )
    assert response.status_code == 200
    with pytest.raises(TradeError, match="Attempt no longer owns"):
        flow.finish(lease)
    with flow.sessions() as db:
        assert db.scalar(select(func.count(Extraction.id))) == 0


def test_source_replacement_keeps_originals_and_old_jobs_historical(flow):
    doc = flow.document().json()
    request = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/processing-jobs",
        {"stage": "EXTRACT"},
    )
    with flow.sessions() as db:
        lease = jobs.claim(db, "historical-test", request.json()["job_id"])
    new = flow.request(
        "POST",
        f"/documents/{doc['id']}/versions",
        {
            "reason": "CLEARER_COPY",
            "reason_text": "Clearer source",
            "primary_attachment_id": flow.attachment(),
        },
        etag=doc["etag"],
    )
    assert new.status_code == 200 or new.status_code == 201, new.text
    flow.finish(lease)
    current = flow.get(f"/documents/{doc['id']}")
    assert current["current_version_id"] != doc["current_version_id"]
    assert current["latest_draft_fact_revision_id"] is None
    with flow.sessions() as db:
        assert db.scalar(select(func.count(Asset.id))) == 2
        assert db.scalar(select(func.count(Extraction.id))) == 1


def test_checks_preserve_price_basis_missing_values_and_freshness(flow):
    doc = prepared(flow)
    response, consignments = flow.mapped(doc)
    assert response.status_code == 201
    doc = flow.get(f"/documents/{doc['id']}")
    response = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/assessment-runs",
        {
            "fact_revision_id": doc["effective_fact_revision_id"],
            "mapping_revision_id": doc["current_mapping_revision_id"],
            "scope": "TRADE",
        },
    )
    assert response.status_code == 202, response.text
    assert worker.run_one(flow.sessions, response.json()["job_id"])
    with flow.sessions() as db:
        assessment = db.scalar(select(Assessment))
        assert assessment is not None
        ident = assessment.id
    view = flow.get(f"/document-assessment-runs/{ident}")
    assert view["freshness"] == "CURRENT"
    price = next(f for f in view["findings"] if f["check_code"] == "DECLARED_PRICE_DIFFERENCE")
    assert price["observed_value_json"] == "1000000"
    assert price["outcome"] == "PASS"
    assert any(f["outcome"] == "UNKNOWN" for f in view["findings"])
    with flow.sessions() as db:
        cn = db.get(Consignment, consignments[0]["id"])
        cn.row_version += 1
        db.commit()
    assert flow.get(f"/document-assessment-runs/{ident}")["freshness"] == "STALE"


def test_immutable_observations_and_fact_revisions(flow):
    doc = prepared(flow)
    with flow.sessions() as db:
        observation = db.scalar(select(Observation))
        observation.raw_text = "tampered"
        with pytest.raises(DBAPIError):
            db.commit()
        db.rollback()
        fact = db.get(FactRevision, doc["effective_fact_revision_id"])
        fact.content_hash = "f" * 64
        with pytest.raises(DBAPIError):
            db.commit()


def test_admin_does_not_automatically_gain_review_authority(flow):
    doc = prepared(flow)
    response = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/processing-jobs",
        {"stage": "EXTRACT"},
        role="seller-approver",
    )
    assert response.status_code == 403


def test_manual_attestation_is_not_live_authority_and_never_fetches_url(flow):
    doc = prepared(flow)
    response = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/manual-attestations",
        {
            "check_type": "GSTIN_AUTHORITY_LOOKUP",
            "target_identifier": "33ABCDE1234F1Z5",
            "portal_source_url": "https://services.gst.gov.in/",
            "observed_at": now().isoformat(),
            "observed_status": "Manually reported",
            "evidence_attachment_ids": [],
        },
    )
    assert response.status_code == 201 and response.json()["method"] == "MANUAL_REPORTED"
    assert (
        flow.get(f"/documents/{doc['id']}")["status_dimensions"]["authority_lookup"]
        == "NOT_CHECKED"
    )


def test_reviewed_sharing_never_shares_raw_capture_and_revocation_is_immediate(flow):
    doc = flow.reviewed(flow.extract(flow.document(visibility="OWNER_ONLY").json()))
    share = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/access-grants",
        {
            "grantee_organization_id": flow.fx["organizations"]["buyer"],
            "access_type": "READ_REVIEWED",
        },
    )
    assert share.status_code == 201, share.text
    buyer = "buyer-receiver"
    assert (
        flow.get(f"/document-fact-revisions/{doc['effective_fact_revision_id']}", buyer)["id"]
        == doc["effective_fact_revision_id"]
    )
    for path in (
        f"/document-versions/{doc['current_version_id']}/extraction-runs",
        f"/document-versions/{doc['current_version_id']}/pages",
    ):
        assert flow.request("GET", path, role=buyer).status_code == 403
    exported = flow.get(f"/document-versions/{doc['current_version_id']}/evidence-manifest", buyer)
    assert exported["extraction_runs"] == [] and exported["derived_artifacts"] == []
    assert "observations" not in exported
    revoked = flow.request(
        "POST",
        f"/document-access-grants/{share.json()['id']}/revocations",
        {"reason": "End sharing"},
    )
    assert revoked.status_code == 200
    assert flow.request("GET", f"/documents/{doc['id']}", role=buyer).status_code == 404


def test_duplicate_alias_preserves_sources_and_cannot_allocate_again(flow):
    original, alias = prepared(flow), prepared(flow)
    response = flow.request(
        "POST",
        f"/documents/{alias['id']}/relationships",
        {
            "to_document_id": original["id"],
            "relationship_type": "DUPLICATE_PRESENTATION_OF",
            "reason": "Same reviewed issued document; preserve clearer presentation as canonical",
        },
        etag=alias["etag"],
    )
    assert response.status_code == 201, response.text
    alias = flow.get(f"/documents/{alias['id']}")
    assert alias["document_total_aggregation"] == "ALIAS_EXCLUDED"
    response, _ = flow.mapped(alias)
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "DUPLICATE_CANONICAL_REVIEW_REQUIRED"
    )
    with flow.sessions() as db:
        assert db.scalar(select(func.count(Asset.id))) == 2


def test_review_head_occ_and_wrong_content_hash_are_rejected(flow):
    doc = prepared(flow)
    wrong = flow.request(
        "POST",
        f"/document-fact-revisions/{doc['effective_fact_revision_id']}/submissions",
        {"content_hash": "0" * 64},
        etag=doc["etag"],
    )
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "REVIEW_HEAD_CHANGED"
    old = flow.request(
        "POST",
        f"/document-fact-revisions/{doc['effective_fact_revision_id']}/submissions",
        {
            "content_hash": flow.get(
                f"/document-fact-revisions/{doc['effective_fact_revision_id']}"
            )["content_hash"]
        },
        etag='"0"',
    )
    assert old.status_code == 409


def test_postgresql_mapping_concurrent_heads_have_one_winner(flow):
    if not flow.postgres:
        pytest.skip("Set TRADE_TEST_DATABASE_URL for PostgreSQL concurrency")
    doc = prepared(flow)
    response, _ = flow.mapped(doc)
    assert response.status_code == 201
    doc = flow.get(f"/documents/{doc['id']}")
    current = response.json()
    body = {k: current[k] for k in ("fact_revision_id", "accepted_trade_revision_id", "mappings")}
    body["base_mapping_revision_id"] = current["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: flow.request(
                    "POST", f"/documents/{doc['id']}/mapping-revisions", body, etag=doc["etag"]
                ),
                range(2),
            )
        )
    assert sorted(r.status_code for r in results) == [201, 409]
    assert len(flow.get(f"/documents/{doc['id']}/mappings")["items"]) == 2


def test_phase2_replanning_can_replace_item_rows_without_destroying_mapping_evidence(flow):
    doc = prepared(flow)
    mapped, consignments = flow.mapped(doc)
    assert mapped.status_code == 201
    cn = consignments[0]
    changed = flow.request(
        "PATCH",
        f"/consignments/{cn['id']}",
        {
            "items": [
                {"line_ref": cn["items"][0]["line_ref"], "allocated_quantity": "30", "uqc": "NOS"}
            ]
        },
        etag=cn["etag"],
    )
    assert changed.status_code == 200, changed.text
    history = flow.get(f"/documents/{doc['id']}/mappings")["items"]
    assert len(history) == 1 and history[0]["freshness"] == "STALE"
    assert history[0]["mappings"][0]["target_snapshot_json"]["allocated_quantity"] == "40.000000"


def test_active_operational_projection_never_discloses_invoice_fields_and_revokes(flow):
    demo = Demo(flow.sessions, flow.fx)
    cn = demo.allocate("40")
    assignment = demo.assignment(cn, 0)
    doc = flow.reviewed(
        flow.extract(flow.document(kind="LR_GR", visibility="OWNER_ONLY", cn=cn["id"]).json())
    )
    grant = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/access-grants",
        {
            "grantee_organization_id": flow.fx["organizations"]["carrier"],
            "access_type": "OPERATIONAL_PROJECTION",
            "assignment_id": assignment["id"],
            "allowed_field_paths": ["header.document_number"],
        },
    )
    assert grant.status_code == 201, grant.text
    projected = flow.get(
        f"/consignments/{cn['id']}/document-operational-projections", "driver-one"
    )["items"]
    assert len(projected) == 1 and projected[0]["fields"] == {
        "header.document_number": "INV-000001"
    }
    assert "grand_total_minor" not in str(projected)
    assert flow.request("GET", f"/documents/{doc['id']}", role="driver-one").status_code == 403
    assert flow.request(
        "GET", f"/consignments/{cn['id']}/document-operational-projections", role="driver-two"
    ).status_code in {403, 404}
    revoked = flow.request(
        "POST",
        f"/document-access-grants/{grant.json()['id']}/revocations",
        {"reason": "End operational sharing"},
    )
    assert revoked.status_code == 200
    assert (
        flow.get(f"/consignments/{cn['id']}/document-operational-projections", "driver-one")[
            "items"
        ]
        == []
    )


def test_queued_comparison_pins_old_plan_and_finishes_as_stale(flow):
    doc = prepared(flow)
    _, consignments = flow.mapped(doc)
    doc = flow.get(f"/documents/{doc['id']}")
    queued = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/assessment-runs",
        {
            "fact_revision_id": doc["effective_fact_revision_id"],
            "mapping_revision_id": doc["current_mapping_revision_id"],
            "scope": "CONSIGNMENT",
            "consignment_ids": [consignments[0]["id"]],
        },
    )
    assert queued.status_code == 202
    cn = consignments[0]
    changed = flow.request(
        "PATCH", f"/consignments/{cn['id']}", {"declared_gross_weight_kg": "500"}, etag=cn["etag"]
    )
    assert changed.status_code == 200, changed.text
    assert worker.run_one(flow.sessions, queued.json()["job_id"])
    with flow.sessions() as db:
        assessed = db.scalar(select(Assessment))
        ident = assessed.id
    result = flow.get(f"/document-assessment-runs/{ident}")
    assert result["freshness"] == "STALE"
    finding = next(f for f in result["findings"] if f["check_code"] == "PACKING_WEIGHT_DIFFERENCE")
    assert finding["expected_value_json"] == "400"


def test_review_timestamp_normalization_does_not_invent_timezone():
    value = schemas.FieldDecision(
        field_path="eway_bill.valid_from_at",
        effective_value="2026-10-12T05:30:00+05:30",
        decision="CORRECTED",
        provenance="HUMAN_TRANSCRIPTION",
        reason="Transcribed printed offset",
    )
    assert value.effective_value == "2026-10-12T00:00:00Z"
    with pytest.raises(ValueError):
        schemas.FieldDecision(
            field_path="eway_bill.valid_from_at",
            effective_value="2026-10-12T05:30:00",
            decision="CORRECTED",
            provenance="HUMAN_TRANSCRIPTION",
            reason="No offset printed",
        )


def test_partial_invoice_price_uses_confirmed_portion_not_whole_order(flow):
    doc = flow.extract(flow.document().json())
    canonical = flow.get(f"/document-fact-revisions/{doc['latest_draft_fact_revision_id']}")[
        "canonical_document_json"
    ]
    canonical["lines"][0].update(quantity="40", taxable_value_minor="400000")
    canonical["totals"].update(
        taxable_subtotal_minor="400000", igst_total_minor="72000", grand_total_minor="472000"
    )
    doc = flow.reviewed(flow.extract(doc, reprocess=True, canonical=canonical))
    cn = Demo(flow.sessions, flow.fx).allocate("40")
    fact = flow.get(f"/document-fact-revisions/{doc['effective_fact_revision_id']}")
    with flow.sessions() as db:
        revision_id = db.get(Trade, flow.fx["trade_id"]).accepted_revision_id
    mapping = flow.request(
        "POST",
        f"/documents/{doc['id']}/mapping-revisions",
        {
            "fact_revision_id": fact["id"],
            "accepted_trade_revision_id": revision_id,
            "mappings": [
                {
                    "document_line_ref": canonical["lines"][0]["document_line_ref"],
                    "trade_line_ref": cn["items"][0]["line_ref"],
                    "target_kind": "CONSIGNMENT_ITEM",
                    "consignment_item_id": cn["items"][0]["id"],
                    "mapped_quantity": "40",
                    "uqc": "NOS",
                }
            ],
        },
        etag=doc["etag"],
    )
    assert mapping.status_code == 201, mapping.text
    doc = flow.get(f"/documents/{doc['id']}")
    queued = flow.request(
        "POST",
        f"/document-versions/{doc['current_version_id']}/assessment-runs",
        {"fact_revision_id": fact["id"], "mapping_revision_id": mapping.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    assert worker.run_one(flow.sessions, queued.json()["job_id"])
    with flow.sessions() as db:
        ident = db.scalar(select(Assessment.id))
    findings = flow.get(f"/document-assessment-runs/{ident}")["findings"]
    price = next(f for f in findings if f["check_code"] == "DECLARED_PRICE_DIFFERENCE")
    assert price["outcome"] == "PASS" and price["expected_value_json"] == "400000"
