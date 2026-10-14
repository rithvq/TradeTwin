"""Phase 6 foundation: real governance, scoped freshness, impacts and driver reporting."""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for name in list(sys.modules):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

from app.compliance import demo as release_demo  # noqa: E402
from app.compliance.clock import instant, use_test_clock  # noqa: E402
from app.corridor import (  # noqa: E402
    adapters,
    events,
    governance,
    impact,
    projection,
    service,
    sources,
)
from app.corridor import schemas as s  # noqa: E402
from app.corridor.geometry import match  # noqa: E402
from app.corridor.models import Incident, SourceItem  # noqa: E402
from app.document_desk.worker import run_one  # noqa: E402
from app.freight import commitments, demo, runs  # noqa: E402
from app.freight.models import Candidate, Quote, Run  # noqa: E402
from app.freight.schemas import CarrierDecision, SelectionDecision, SelectionInput  # noqa: E402
from app.operations.models import Consignment  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import Trade  # noqa: E402


@pytest.fixture()
def fx(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    engine = create_engine(url or f"sqlite:///{tmp_path / 'corridor.db'}")
    schema = f"corridor_test_{uuid4().hex}" if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        if not url:
            connection.execute("PRAGMA foreign_keys=ON")

    migrate(engine)
    sessions = sessionmaker(engine)
    data = demo.seed(sessions, "corridor-foundation-test")
    with sessions() as db:
        job_id = db.get(Run, data["run_id"]).job_id
    assert run_one(sessions, job_id)
    try:
        yield sessions, data
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def actors(db, data):
    return release_demo.actor(db, data, "seller-operations"), release_demo.actor(
        db, data, "seller-approver"
    )


def event_fixture(
    db,
    data,
    state="29",
    kind="ROAD_CLOSURE",
    effect="EXCLUDE_EDGE",
    direction="BOTH",
    published=True,
):
    author, reviewer = actors(db, data)
    at = instant(db)
    source = sources.create(
        db,
        author,
        None,
        s.ConnectionInput(
            provider_code="SIMULATION",
            environment="SIMULATION",
            source_kind="SIMULATION",
            documented_endpoint_reference="Synthetic retained source",
            endpoint_contract_version="SIMULATION_V1",
            approved_https_hosts=[],
            covered_state_codes=[state],
            covered_event_kinds=[kind],
            maximum_item_age_seconds=86400,
            retention_policy="PERMITTED_ARCHIVE",
            source_item_storage_allowed=True,
            attribution_text="SIMULATION ONLY",
        ),
    )
    author.if_match = source["etag"]
    sources.status(
        db,
        author,
        source["id"],
        s.ConnectionStatus(status="CONFIGURED", reason="Synthetic archival source"),
    )
    item = sources.manual(
        db,
        author,
        None,
        s.SourceInput(
            source_connection_id=source["id"],
            provider_item_key=str(uuid4()),
            source_issued_at=at,
            retrieved_at=at,
            source_reference="SIMULATION synthetic road advisory",
            payload_sha256="a" * 64,
            mime_type="application/json",
        ),
    )
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.run_id == data["run_id"], Candidate.quote_revision_id == data["quotes"]["A"]
        )
    )
    route = candidate.candidate_json["scenarios"]["BASE"]["route"]
    head = events.incident(
        db, author, None, s.IncidentInput(environment="SIMULATION", visibility="PUBLIC_APPROVED")
    )
    author.if_match = head["etag"]
    row = events.create(
        db,
        author,
        head["id"],
        s.EventInput(
            source_item_id=item["id"],
            event_kind=kind,
            headline="Synthetic closure",
            summary="Synthetic source-backed road impact",
            source_sender="synthetic",
            source_identifier=str(uuid4()),
            source_sent_at=at,
            severity="SEVERE",
            assessed_effective_from=at,
            assessed_effective_until=at + timedelta(days=1),
            operational_review_due_at=at + timedelta(hours=6),
            time_interpretation="UTC synthetic time",
            geography=s.Geography(
                geometry_kind="ROAD_EDGE_SET",
                dataset_revision_id=route["dataset_revision_id"],
                edge_keys=[route["ordered_edge_keys"][0]],
                state_codes=[state],
                direction=direction,
                precision="EXACT_EDGE",
                basis="SIMULATION",
            ),
            report_basis="SIMULATION",
        ),
    )
    policy = governance.create(
        db,
        author,
        None,
        s.PolicyInput(
            environment="SIMULATION",
            policy_code="SYNTHETIC_CLOSURE_" + str(uuid4()),
            event_kinds=[kind],
            state_codes=[state],
            source_kinds=["SIMULATION"],
            effect=effect,
            minimum_precision="EXACT_EDGE",
            maximum_source_age_seconds=86400,
            missing_coverage_action="SHOW_LIMITATION",
            release_condition="REOPENING_EVIDENCE",
            source_references=["synthetic application policy"],
            effective_from=at,
            effective_until=at + timedelta(days=2),
        ),
    )
    governance.decide(
        db,
        reviewer,
        policy["id"],
        s.Review(
            content_hash=policy["content_hash"], decision="APPROVE", reason="Independently reviewed"
        ),
    )
    governance.decide(
        db,
        reviewer,
        policy["id"],
        s.Exact(content_hash=policy["content_hash"], reason="Synthetic published policy"),
        publish=True,
    )
    if published:
        events.review(
            db,
            reviewer,
            row["id"],
            s.Review(
                content_hash=row["content_hash"],
                decision="APPROVE",
                reason="Independent source interpretation",
            ),
        )
        events.publish(
            db,
            reviewer,
            row["id"],
            s.Exact(content_hash=row["content_hash"], reason="Approved synthetic event"),
        )
    return row, route


def commit(db, data):
    cn = db.get(Consignment, data["consignment_id"])
    run = db.get(Run, data["run_id"])
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.run_id == run.id, Candidate.quote_revision_id == data["quotes"]["A"]
        )
    )
    quote = db.get(Quote, candidate.quote_revision_id)
    author, reviewer = actors(db, data)
    author.if_match = f'"{cn.row_version}"'
    proposal = commitments.propose(
        db,
        author,
        cn.id,
        SelectionInput(
            run_id=run.id,
            candidate_id=candidate.id,
            candidate_hash=candidate.content_hash,
            quote_revision_id=quote.id,
            quote_hash=quote.content_hash,
            scenario_code="BASE",
            expected_existing_assignment_id=cn.active_assignment_id,
            expected_consignment_row_version=cn.row_version,
            expected_context_version=run.input_json["context"]["compliance_context_version"],
        ),
    )
    reviewer.if_match = proposal["etag"]
    approval = commitments.approve(
        db,
        reviewer,
        proposal["id"],
        SelectionDecision(
            proposal_hash=proposal["proposal_hash"],
            quote_hash=proposal["quote_hash"],
            decision="APPROVE",
            acknowledged_limitation_codes=[
                "ESTIMATE_NOT_GUARANTEE",
                "AVAILABILITY_NOT_RESERVATION",
                "FRESH_PHASE4_RELEASE_REQUIRED",
            ],
            reason="Exact synthetic price",
        ),
        "PAYER",
    )
    carrier = release_demo.actor(db, data, "carrier-dispatcher")
    carrier.if_match = approval["etag"]
    return commitments.accept(
        db,
        carrier,
        proposal["id"],
        CarrierDecision(
            proposal_hash=proposal["proposal_hash"],
            quote_hash=proposal["quote_hash"],
            proposed_assignment_id=approval["proposed_assignment_id"],
            decision="ACCEPT",
            reason="Synthetic carrier confirmation",
        ),
    )


def test_draft_has_no_operational_effect_and_self_review_is_rejected(fx):
    sessions, data = fx
    with sessions() as db:
        row, _ = event_fixture(db, data, published=False)
        author, _ = actors(db, data)
        with pytest.raises(TradeError) as failure:
            events.review(
                db,
                author,
                row["id"],
                s.Review(
                    content_hash=row["content_hash"], decision="APPROVE", reason="Self review"
                ),
            )
        assert failure.value.status == 403
        cn = db.get(Consignment, data["consignment_id"])
        captured = projection.capture(db, db.get(Trade, cn.trade_id), cn)
        assert captured["events"] == []


def test_scoped_publication_stales_existing_run_without_repricing(fx):
    sessions, data = fx
    with sessions() as db:
        cn = db.get(Consignment, data["consignment_id"])
        trade = db.get(Trade, cn.trade_id)
        run = db.get(Run, data["run_id"])
        old_price = run.result_json["candidates"][0]["scenarios"]["BASE"]["cost"]
        assert runs.fresh(db, run, trade, cn) == "CURRENT"
        event_fixture(db, data)
        assert runs.fresh(db, run, trade, cn) == "STALE"
        quote = db.get(Quote, data["quotes"]["A"])
        assert (
            quote.source_context_hash == runs.base_context(db, trade, cn)["planning_context_hash"]
        )
        assert run.result_json["candidates"][0]["scenarios"]["BASE"]["cost"] == old_price


def test_actual_plan_blocks_and_expiry_does_not_prove_reopening(fx):
    sessions, data = fx
    with sessions() as db:
        commit(db, data)
        row, _ = event_fixture(db, data)
        author, reviewer = actors(db, data)
        cn = db.get(Consignment, data["consignment_id"])
        trade = db.get(Trade, cn.trade_id)
        assert projection.dependency(db, trade, cn)["outcome"] == "BLOCKED", impact.evaluate_plan(
            db, projection.plan(db, cn), projection.capture(db, trade, cn)
        )
        with pytest.raises(TradeError, match="corridor"):
            service.guard(db, trade, cn)
        events.withdraw(
            db, reviewer, row["id"], s.Reason(reason="Provider cancellation is not reopening")
        )
        assert projection.dependency(db, trade, cn)["outcome"] == "NEEDS_REVIEW"
        future = instant(db) + timedelta(days=3)
        with use_test_clock(lambda: future):
            assert projection.dependency(db, trade, cn)["outcome"] == "NEEDS_REVIEW"
        data_view = service.dynamic_context(db, author, cn.id)
        assert data_view["impact"]["contract_price_changed"] is False


def test_driver_response_is_not_stop_verification_or_spending_authority(fx):
    sessions, data = fx
    with sessions() as db:
        commit(db, data)
        event_fixture(db, data)
        author, coordinator = actors(db, data)
        cn = db.get(Consignment, data["consignment_id"])
        dynamic = service.dynamic_context(db, author, cn.id)
        author.if_match = dynamic["etag"]
        assessment = service.reassess(
            db,
            author,
            cn.id,
            s.Reassessment(
                expected_context_hash=dynamic["dynamic_context_hash"],
                current_route_plan_revision_id=dynamic["current_route_plan_revision_id"],
            ),
        )
        coordinator.if_match = f'"{cn.row_version}"'
        case = service.create_case(
            db,
            coordinator,
            cn.id,
            s.CaseInput(
                assessment_id=assessment["id"],
                current_route_plan_revision_id=dynamic["current_route_plan_revision_id"],
                reason="Operational protection",
            ),
        )
        driver = release_demo.actor(db, data, "driver-one")
        driver.if_match = case["etag"]
        result = service.driver_response(
            db,
            driver,
            case["id"],
            s.DriverInput(
                action="CANNOT_STOP_SAFELY",
                observed_at=instant(db),
                location_method="NONE",
                reason="Looking for safe parking",
            ),
        )
        assert result["case"]["motion"] == "UNKNOWN"
        assert not result["case"]["resume_authorised"] and not result["financial_approval"]
        driver.if_match = result["case"]["etag"]
        result = service.driver_response(
            db,
            driver,
            case["id"],
            s.DriverInput(
                action="CONFIRM_REPORTED_STOPPED",
                observed_at=instant(db),
                location_method="NONE",
                safe_stop=True,
                reason="Reported safely parked",
            ),
        )
        assert result["case"]["motion"] == "REPORTED_STOPPED"
        assert result["stop_verified"] is False
        assert result["case"]["anchor_approved"] is False


def test_retained_source_and_assessment_immutable(fx):
    sessions, data = fx
    with sessions() as db:
        event_fixture(db, data)
        db.commit()
    with sessions() as db:
        item = db.scalar(select(SourceItem))
        item.content_hash = "b" * 64
        with pytest.raises(DBAPIError, match="immutable"):
            db.commit()


def test_cancel_before_original_blocks_late_delivery_across_timezone_forms(fx):
    sessions, data = fx
    with sessions() as db:
        original, _ = event_fixture(db, data, published=False)
        author, reviewer = actors(db, data)
        original_item = db.get(SourceItem, original["source_item_id"])
        item = sources.manual(
            db,
            author,
            None,
            s.SourceInput(
                source_connection_id=original_item.source_connection_id,
                provider_item_key="cancellation-" + str(uuid4()),
                source_issued_at=instant(db),
                retrieved_at=instant(db),
                source_reference="Synthetic CAP cancellation",
                payload_sha256="c" * 64,
                mime_type="application/xml",
            ),
        )
        payload = dict(original["event_json"])
        payload.update(
            source_item_id=item["id"],
            source_identifier="cancel-new",
            source_message_type="CANCEL",
            event_kind="OTHER",
        )
        source_sent = payload["source_sent_at"].replace("+00:00", "Z")
        payload["upstream_references"] = [
            f"{payload['source_sender']},{original['event_json']['source_identifier']},{source_sent}"
        ]
        head = db.get(Incident, original["incident_id"])
        author.if_match = f'"{head.row_version}"'
        cancellation = events.create(db, author, head.id, s.EventInput.model_validate(payload))
        for row in [cancellation, original]:
            events.review(
                db,
                reviewer,
                row["id"],
                s.Review(
                    content_hash=row["content_hash"],
                    decision="APPROVE",
                    reason="Independent synthetic review",
                ),
            )
        events.publish(
            db,
            reviewer,
            cancellation["id"],
            s.Exact(content_hash=cancellation["content_hash"], reason="Publish cancellation first"),
        )
        with pytest.raises(TradeError) as rejected:
            events.publish(
                db,
                reviewer,
                original["id"],
                s.Exact(content_hash=original["content_hash"], reason="Late original delivery"),
            )
        assert rejected.value.code == "UPSTREAM_SUPERSEDED"


def test_unpublished_future_policy_has_no_dispatch_dependency(fx):
    sessions, data = fx
    with sessions() as db:
        author, _ = actors(db, data)
        cn = db.get(Consignment, data["consignment_id"])
        trade = db.get(Trade, cn.trade_id)
        before = projection.dependency(db, trade, cn)
        at = instant(db)
        governance.create(
            db,
            author,
            None,
            s.PolicyInput(
                environment="SIMULATION",
                policy_code="UNPUBLISHED_FUTURE",
                event_kinds=["WEATHER_WARNING"],
                state_codes=["29"],
                source_kinds=["SIMULATION"],
                effect="ADVISORY_ONLY",
                minimum_precision="ADMIN_AREA",
                maximum_source_age_seconds=3600,
                missing_coverage_action="SHOW_LIMITATION",
                release_condition="NOT_APPLICABLE",
                source_references=["Draft only"],
                effective_from=at + timedelta(hours=1),
                effective_until=at + timedelta(hours=2),
            ),
        )
        assert projection.dependency(db, trade, cn) == before


@pytest.mark.parametrize("direction,expected", [("BOTH", "EXACT_EDGE"), ("FORWARD", "EXACT_EDGE")])
def test_exact_dataset_edge_match(direction, expected):
    assert (
        match(
            {"dataset_revision_id": "a", "edge_key": "one", "state_codes": ["27"]},
            {
                "geometry_kind": "ROAD_EDGE_SET",
                "dataset_revision_id": "a",
                "edge_keys": ["one"],
                "state_codes": ["27"],
                "direction": direction,
            },
        )
        == expected
    )


def test_polygon_bbox_overlap_is_not_exact_intersection():
    geo = {
        "geometry_kind": "POLYGON",
        "geojson": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [0, 2], [0, 0]]]},
    }
    assert match({"coordinates": [[1.6, 1.6], [1.8, 1.8]]}, geo) == "NONE"
    assert match({"coordinates": [[0.2, 0.2], [0.3, 0.3]]}, geo) == "GEOMETRY_INTERSECTION"


@pytest.mark.parametrize(
    "code,nowcast,warning",
    [
        ("1", "GREEN", "RED"),
        ("2", "YELLOW", "ORANGE"),
        ("3", "ORANGE", "YELLOW"),
        ("4", "RED", "GREEN"),
        ("9", None, None),
    ],
)
def test_imd_opposite_color_contracts(code, nowcast, warning):
    nc = adapters.weather(
        json.dumps(
            [
                {
                    "District_ID": "573",
                    "Date": "2026-10-14",
                    "toi": "2330",
                    "Vupto": "0030",
                    "color": code,
                }
            ]
        ).encode(),
        "IMD_NOWCAST_V1",
        {"573": "DISTRICT-REVIEWED"},
    )[0]
    wr = adapters.weather(
        json.dumps([{"Obj_id": "573", "Date": "2026-10-14", "Day1_Color": code}]).encode(),
        "IMD_DISTRICT_WARNING_V1",
        {"573": "DISTRICT-REVIEWED"},
    )[0]
    assert nc["severity"] == nowcast and wr["severity"] == warning
    assert nc["effective_until"].startswith("2026-10-14T19:00")
    assert nc["district_code"] != "573"


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE a [<!ENTITY x "payload">]><a>&x;</a>',
        b'<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
        b'<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="file:///secret"/>'
        b"</alert>",
        b"x" * (adapters.MAX_BYTES + 1),
    ],
    ids=["dtd", "xinclude", "oversize"],
)
def test_cap_rejects_unsafe_sources(payload):
    from defusedxml.common import DefusedXmlException

    with pytest.raises((ValueError, DefusedXmlException)):
        adapters.cap(payload)


def test_cap_actual_cancel_is_not_publishable_or_reopening():
    value = adapters.cap(
        b'<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
        b"<identifier>cancel1</identifier><sender>agency</sender>"
        b"<sent>2026-10-14T10:00:00+05:30</sent><status>Actual</status>"
        b"<msgType>Cancel</msgType><scope>Public</scope>"
        b"<references>agency,original,2026-10-14T09:00:00+05:30</references></alert>"
    )
    assert not value["operationally_publishable"] and value["references"]


@pytest.mark.parametrize("boundary", ["2026-10-14T01:00:00+00:00", "2026-10-14T02:00:00+00:00"])
def test_half_open_temporal_boundaries(boundary):
    event = {
        "assessed_effective_from": "2026-10-14T01:00:00+00:00",
        "assessed_effective_until": "2026-10-14T02:00:00+00:00",
    }
    section = {
        "entry_at": boundary,
        "exit_at": (datetime.fromisoformat(boundary) + timedelta(hours=1)).isoformat(),
    }
    assert impact.temporal(section, event, 0) == (
        "OVERLAP" if boundary.endswith("01:00:00+00:00") else "NONE"
    )
