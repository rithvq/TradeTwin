"""Real ranking/provider boundaries and leased, tenant-scoped route-study integration."""

import json
import os
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for module in list(sys.modules):
    if module == "app" or module.startswith("app."):
        del sys.modules[module]

from app.compliance import demo as release_demo  # noqa: E402
from app.compliance.clock import use_test_clock  # noqa: E402
from app.document_desk.models import Job  # noqa: E402
from app.document_desk.worker import run_one  # noqa: E402
from app.freight import demo  # noqa: E402
from app.freight.models import RoutePlan, Template  # noqa: E402
from app.freight_routes import engine as route_engine  # noqa: E402
from app.freight_routes import geography, history, jobs, ors, weather  # noqa: E402
from app.freight_routes.models import RouteStudy  # noqa: E402
from app.freight_routes.network import document  # noqa: E402
from app.freight_routes.ranking import compare  # noqa: E402
from app.freight_routes.schemas import StudyInput, Weights  # noqa: E402
from app.operations.models import Booking, Consignment, Event  # noqa: E402
from app.trades.errors import TradeError  # noqa: E402
from app.trades.migrate import migrate  # noqa: E402
from app.trades.models import Grant, Membership  # noqa: E402


def candidate(ident, distance=100, duration=100, exposure=10, feasibility="ASSESSED"):
    return {
        "id": ident,
        "feasibility": feasibility,
        "reason_codes": [],
        "driving_seconds": duration,
        "metrics": {
            "distance": distance,
            "duration": duration,
            "road_weather_exposure": exposure,
            "state_transit_history": None,
            "toll_exposure": 0,
        },
    }


def test_weights_change_preference_but_cannot_override_exclusions_or_reward_unknowns():
    routes = [
        candidate("short", 100, 200),
        candidate("fast", 120, 100),
        candidate("closed", 50, 50, feasibility="EXCLUDED"),
    ]
    assert compare(routes, {"distance": 10000})["best_candidate_id"] == "short"
    assert compare(routes, {"duration": 10000})["best_candidate_id"] == "fast"
    routes[0]["metrics"]["road_weather_exposure"] = None
    value = compare(routes, Weights().model_dump())
    assert "road_weather_exposure" in value["omitted_factors"]
    assert all(
        "road_weather_exposure" not in [p["factor"] for p in r["contributions"]]
        for r in value["rankings"]
    )
    assert len(value["rankings"]) == 2
    assert compare([routes[-1]], {"distance": 10000})["best_candidate_id"] is None
    assert compare([routes[0]], {"distance": 10000})["comparison_status"] == "SINGLE_CANDIDATE"


def road_snapshot():
    return {
        "truck": {
            "height_m": "3.7",
            "width_m": "2.45",
            "length_m": "9",
            "tare_kg": "6500",
            "axle_load_kg": "6000",
        },
        "cargo_weight_kg": "400",
        "hazardous_declared": False,
        "pickup": {"coordinates": [77.59, 12.97], "state_code": "29"},
        "drop": {"coordinates": [80.27, 13.08], "state_code": "33"},
        "corridor": {
            "events": [],
            "policies": [],
            "coverage": {"status": "NOT_CONFIGURED", "missing_scopes": [], "checked_sources": []},
        },
    }


def provider_response(coords=None):
    return {
        "features": [
            {
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords or [[77.59, 12.97], [78.5, 13.0], [80.27, 13.08]],
                },
                "properties": {
                    "summary": {"distance": 350000, "duration": 21600},
                    "extras": {
                        "waytype": {"summary": [{"value": 1, "distance": 350000}]},
                        "tollways": {"summary": [{"value": 1, "distance": 100000}]},
                    },
                },
            }
        ]
    }


def test_live_hgv_units_deduplication_and_no_fallback(monkeypatch):
    monkeypatch.setenv("ALLOW_EXTERNAL_ROUTING", "true")
    monkeypatch.setenv("ORS_API_KEY", "test-only-secret")
    monkeypatch.delenv("ORS_DIRECTIONS_URL", raising=False)
    bodies = []

    def provider(request):
        assert request.headers["Authorization"] == "test-only-secret"
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json=provider_response())

    routes, failures = ors.fetch(road_snapshot(), httpx.MockTransport(provider))
    assert len(routes) == 1 and not failures and len(bodies) == 3
    restrictions = bodies[0]["options"]["profile_params"]["restrictions"]
    assert restrictions == {
        "height": 3.7,
        "width": 2.45,
        "length": 9.0,
        "axleload": 6.0,
        "weight": 6.9,
        "hazmat": False,
    }
    assert {b["preference"] for b in bodies} == {"fastest", "shortest"}
    assert "test-only-secret" not in json.dumps(routes)
    with pytest.raises(TradeError, match="No live HGV"):
        ors.fetch(road_snapshot(), httpx.MockTransport(lambda _: httpx.Response(429)))
    monkeypatch.setenv(
        "ORS_DIRECTIONS_URL", "https://unapproved.example/v2/directions/driving-hgv/json"
    )
    with pytest.raises(TradeError) as error:
        ors.endpoint()
    assert error.value.code == "ROUTE_SOURCE_NOT_APPROVED"


def test_network_does_not_forward_secret_to_redirect_or_accept_oversized_data():
    calls = []

    def provider(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(TradeError):
            document(
                client,
                "POST",
                "https://api.heigit.org/",
                hosts=ors.HOSTS,
                headers={"Authorization": "test-secret"},
            )
    assert len(calls) == 1
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 50))
    ) as client:
        with pytest.raises(TradeError) as error:
            document(client, "GET", "https://api.heigit.org/", hosts=ors.HOSTS, limit=10)
    assert error.value.code == "ROUTE_SOURCE_INVALID"


def boundaries():
    def box(code, left, right):
        return {
            "type": "Feature",
            "properties": {"state_code": code},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[left, 0], [right, 0], [right, 2], [left, 2], [left, 0]]],
            },
        }

    return geography.prepare(
        {"type": "FeatureCollection", "features": [box("29", 0, 1), box("33", 1, 2)]},
        {"name": "Synthetic test boundaries"},
    )


def test_state_crossing_reentry_and_unmapped_intervals_are_preserved():
    assert geography.state_code({"shapeName": "Karnātaka"}) == "29"
    assert geography.state_code({"shapeName": "Tamil Nādu"}) == "33"
    assert geography.state_code({"shapeName": "Mahārāshtra"}) == "27"
    result = geography.corridor([[0.5, 1], [1.5, 1], [0.5, 1]], boundaries())
    assert result["state_sequence"] == ["29", "33", "29"]
    result = geography.corridor([[0.5, 1], [3, 1]], boundaries())
    assert result["state_sequence"] == ["29", "33", None]
    assert result["mapping_status"] == "PARTIAL"
    assert geography.corridor([[1, 0.5], [1, 1.5]], boundaries())["state_sequence"] == [None]


def test_forecast_failure_or_missing_values_are_unknown_not_good_weather(monkeypatch):
    monkeypatch.setenv("FREIGHT_WEATHER_PLAN", "NON_COMMERCIAL")
    route = ors.parse(provider_response(), "test", "https://api.heigit.org/")[0]
    at = datetime.now(UTC)
    hour = int(at.timestamp()) // 3600 * 3600
    rows = [
        {
            "hourly": {
                "time": list(range(hour, hour + 12 * 3600, 3600)),
                "precipitation": [0] * 12,
                "wind_gusts_10m": [20] * 12,
                "visibility": [10000] * 12,
            }
        }
        for _ in range(7)
    ]
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))
    ) as client:
        assert weather.fetch(client, [route], at, True)[route["id"]]["exposure"] == 0
        rows[3]["hourly"]["visibility"] = [None] * 12
        result = weather.fetch(client, [route], at, True)[route["id"]]
        assert result["exposure"] is None
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        assert weather.fetch(client, [route], at, True)[route["id"]]["status"] == "UNAVAILABLE"


def test_reviewed_closure_excludes_short_road_and_requests_a_public_detour(monkeypatch):
    snapshot = road_snapshot()
    at = datetime.now(UTC)
    snapshot["request"] = {"departure_at": at.isoformat()}
    polygon = {
        "type": "Polygon",
        "coordinates": [[[78, 12.9], [79, 12.9], [79, 13.1], [78, 13.1], [78, 12.9]]],
    }
    snapshot["corridor"]["events"] = [
        {
            "id": "closure",
            "incident_id": "incident",
            "hash": "a" * 64,
            "state": "ACTIVE",
            "source_stale": False,
            "connection_status": "CONFIGURED",
            "public_geometry": True,
            "source_kind": "MANUAL_OBSERVATION",
            "source_sent_at": at.isoformat(),
            "source_reference": "https://example.gov.in/closure",
            "event_kind": "ROAD_CLOSURE",
            "headline": "Reviewed closure",
            "limitations": [],
            "independence_group": None,
            "vehicle_profile_codes": [],
            "cargo_profile_codes": [],
            "assessed_effective_from": (at - timedelta(hours=1)).isoformat(),
            "assessed_effective_until": (at + timedelta(hours=12)).isoformat(),
            "geography": {
                "geometry_kind": "POLYGON",
                "geojson": polygon,
                "state_codes": ["29", "33"],
                "direction": "BOTH",
                "precision": "SOURCE_POLYGON",
            },
        }
    ]
    snapshot["corridor"]["policies"] = [
        {
            "id": "reviewed-policy",
            "hash": "b" * 64,
            "event_kinds": ["ROAD_CLOSURE"],
            "source_kinds": ["MANUAL_OBSERVATION"],
            "state_codes": [],
            "effect": "EXCLUDE_EDGE",
            "minimum_precision": "SOURCE_POLYGON",
            "maximum_source_age_seconds": 86400,
            "vehicle_profile_codes": [],
            "cargo_profile_codes": [],
            "missing_coverage_action": "SHOW_LIMITATION",
        }
    ]
    routes = ors.parse(provider_response(), "short", "https://api.heigit.org/")
    assert ors.closure_avoidance(snapshot, routes)["type"] == "Polygon"
    snapshot["corridor"]["events"][0]["public_geometry"] = False
    assert ors.closure_avoidance(snapshot, routes) is None
    snapshot["corridor"]["events"][0]["public_geometry"] = True
    monkeypatch.setenv("ALLOW_EXTERNAL_ROUTING", "true")
    monkeypatch.setenv("ORS_API_KEY", "test-secret")
    monkeypatch.delenv("ORS_DIRECTIONS_URL", raising=False)
    requests = []

    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        detour = "avoid_polygons" in body["options"]
        return httpx.Response(
            200,
            json=provider_response(
                [[77.59, 12.97], [78.5, 14], [80.27, 13.08]] if detour else None
            ),
        )

    alternatives, failures = ors.fetch(snapshot, httpx.MockTransport(provider))
    assert len(alternatives) == 2 and not failures
    assert len(requests) == 4
    assert requests[-1]["options"]["avoid_polygons"]["type"] == "Polygon"
    snapshot.update(
        execution_mode="SIMULATION",
        history=[],
        permit_coverage={"covered_states": [], "valid_until": None},
        policy={"sources": [], "packs": [], "supported_corridors": []},
    )
    snapshot["request"].update(
        source_mode="LIVE",
        include_weather=False,
        weights=Weights().model_dump(),
        planned_stop_seconds=0,
    )
    monkeypatch.setattr(ors, "fetch", lambda *_: (deepcopy(alternatives), []))
    monkeypatch.setattr(geography, "load", lambda _: None)
    value = route_engine.evaluate(snapshot, checked_at=at)
    assert value["candidates"][0]["feasibility"] == "EXCLUDED"
    assert value["comparison"]["best_candidate_id"] == alternatives[1]["id"]


def test_corridor_memory_requires_enough_matching_directional_observations():
    values = [
        {"state_sequence": ["29", "33"], "extra_seconds": s, "observed_at": "2026-10-27T00:00:00Z"}
        for s in (100, 500, 300)
    ]
    assert history.summary(values, ["29", "33"])["ranking_extra_seconds"] == 300
    assert history.summary(values[:2], ["29", "33"])["ranking_extra_seconds"] is None
    assert history.summary(values, ["33", "29"])["sample_count"] == 0


@pytest.fixture()
def route_env(tmp_path):
    url = os.getenv("TRADE_TEST_DATABASE_URL")
    engine = create_engine(url or f"sqlite:///{tmp_path / 'route.db'}")
    schema = f"routes_test_{uuid4().hex}" if url else None
    if schema:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        if not url:
            connection.execute("PRAGMA foreign_keys=ON")

    migrate(engine)
    sessions = sessionmaker(engine)
    fx = demo.seed(sessions, "route-study-tests")
    try:
        yield sessions, fx
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def queue_study(sessions, fx):
    with sessions() as db:
        dataset = db.get(Template, next(iter(fx["routes"].values()))).dataset_revision_id
        payload = StudyInput(
            source_mode="RETAINED",
            dataset_revision_id=dataset,
            departure_at=datetime.now(UTC) + timedelta(hours=1),
            include_weather=False,
        )
        ctx = release_demo.actor(db, fx, "seller-operations")
        value = jobs.request(db, ctx, fx["consignment_id"], payload)
        ident = value["id"]
        job_id = db.get(RouteStudy, ident).job_id
        db.commit()
    return ident, job_id


def test_leased_study_is_current_scoped_and_does_not_commit_operational_changes(route_env):
    sessions, fx = route_env
    ident, job_id = queue_study(sessions, fx)
    with sessions() as db:
        before = [
            db.scalar(select(func.count()).select_from(m)) for m in (Booking, Event, RoutePlan)
        ]
    assert run_one(sessions, job_id)
    with sessions() as db:
        assert db.get(Job, job_id).status == "SUCCEEDED", db.get(Job, job_id).last_error_code
        ctx = release_demo.actor(db, fx, "seller-operations")
        value = jobs.read(db, ctx, ident)
        assert value["freshness"] == "CURRENT", value
        assert len(value["result"]["candidates"]) >= 2
        assert value["result"]["comparison"]["best_candidate_id"] is not None
        assert before == [
            db.scalar(select(func.count()).select_from(m)) for m in (Booking, Event, RoutePlan)
        ]
        assert "dependency_hash" not in json.dumps(value)
        other = release_demo.actor(db, fx, "buyer-receiver")
        with pytest.raises(TradeError):
            jobs.read(db, other, ident)
        with use_test_clock(lambda: datetime.now(UTC) + timedelta(minutes=16)):
            assert jobs.read(db, ctx, ident)["result"]["comparison"]["best_candidate_id"] is None
    with sessions() as db:
        with pytest.raises(DatabaseError):
            db.get(RouteStudy, ident).job_state = "QUEUED"
            db.commit()


def test_context_changes_during_network_work_publish_only_a_stale_comparison(route_env):
    sessions, fx = route_env
    ident, job_id = queue_study(sessions, fx)

    def process(lease):
        output = jobs.process(sessions, lease)
        with sessions() as db:
            cn = db.get(Consignment, fx["consignment_id"])
            cn.planning_status = "CANCELLED"
            db.commit()
        return output

    assert run_one(sessions, job_id, processor=process)
    with sessions() as db:
        value = jobs.read(db, release_demo.actor(db, fx, "seller-operations"), ident)
        assert value["freshness"] == "STALE"
        assert value["result"]["comparison"]["best_candidate_id"] is None


def test_revocation_during_provider_work_cannot_publish_a_recommendation(route_env):
    sessions, fx = route_env
    ident, job_id = queue_study(sessions, fx)

    def process(lease):
        output = jobs.process(sessions, lease)
        with sessions() as db:
            member = db.scalar(
                select(Membership).where(
                    Membership.user_id == fx["users"]["seller-operations"],
                    Membership.organization_id == fx["organizations"]["seller"],
                )
            )
            for grant in db.scalars(
                select(Grant).where(
                    Grant.membership_id == member.id,
                    Grant.permission_code == "tradetwin.plan.prepare",
                )
            ):
                grant.revoked_at = datetime.now(UTC)
            db.commit()
        return output

    assert run_one(sessions, job_id, processor=process)
    with sessions() as db:
        assert db.get(Job, job_id).status == "FAILED"
        assert db.get(RouteStudy, ident).result_json is None


def test_two_worker_attempts_publish_only_one_study(route_env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event as Signal

    sessions, fx = route_env
    ident, job_id = queue_study(sessions, fx)
    entered, release = Signal(), Signal()

    def process(lease):
        entered.set()
        assert release.wait(15)
        return jobs.process(sessions, lease)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(run_one, sessions, job_id, process)
        try:
            assert entered.wait(15)
            assert run_one(sessions, job_id) is False
        finally:
            release.set()
        assert first.result(timeout=30)
    with sessions() as db:
        assert db.get(RouteStudy, ident).job_state == "COMPLETED"
        assert db.get(Job, job_id).attempt_count == 1


def test_provider_failure_preserves_its_reason_and_never_publishes_fallback_data(route_env):
    sessions, fx = route_env
    ident, job_id = queue_study(sessions, fx)

    def process(_):
        raise TradeError("ROUTE_SOURCE_RATE_LIMITED", "Route provider limit reached.", status=503)

    assert run_one(sessions, job_id, processor=process)
    with sessions() as db:
        value = jobs.read(db, release_demo.actor(db, fx, "seller-operations"), ident)
        assert value["error_code"] == "ROUTE_SOURCE_RATE_LIMITED"
        assert value["job_state"] == "FAILED" and value["result"] is None


def test_engine_permit_expiry_and_uncovered_state_exclude_routes(monkeypatch):
    snapshot = road_snapshot()
    at = datetime.now(UTC)
    snapshot.update(
        execution_mode="PRODUCTION",
        history=[],
        request={
            "source_mode": "LIVE",
            "include_weather": False,
            "departure_at": at.isoformat(),
            "planned_stop_seconds": 0,
            "weights": Weights().model_dump(),
        },
        permit_coverage={"covered_states": ["29"], "valid_until": None},
        policy={"sources": [], "packs": [], "supported_corridors": [["29", "33"]]},
    )
    routes = ors.parse(provider_response([[0.5, 1], [1.5, 1]]), "test", "https://api.heigit.org/")
    monkeypatch.setattr(ors, "fetch", lambda *_: (deepcopy(routes), []))
    monkeypatch.setattr(geography, "load", lambda _: boundaries())
    value = route_engine.evaluate(snapshot, checked_at=at)
    assert value["comparison"]["best_candidate_id"] is None
    assert "CURRENT_PERMIT_DOES_NOT_COVER_CORRIDOR" in value["candidates"][0]["reason_codes"]
    snapshot["permit_coverage"] = {
        "covered_states": ["29", "33"],
        "valid_until": (at + timedelta(minutes=5)).isoformat(),
    }
    value = route_engine.evaluate(snapshot, checked_at=at)
    assert "PERMIT_EXPIRES_BEFORE_ESTIMATED_ARRIVAL" in value["candidates"][0]["reason_codes"]
