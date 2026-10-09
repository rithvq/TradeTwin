"""Exercise real HTTP service boundaries; --local uses isolated temporary SQLite stores."""

import argparse
import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {
    "api": 8000,
    "shipment": 8011,
    "compliance": 8012,
    "document": 8013,
    "intelligence": 8014,
}


def infrastructure_environment(stack):
    import psycopg
    from minio import Minio
    from psycopg import sql
    from sqlalchemy.engine import URL

    config = {**dotenv_values(ROOT / ".env.example"), **dotenv_values(ROOT / ".env"), **os.environ}
    name = "tradetwin_audit_" + uuid.uuid4().hex[:12]
    connection_args = {
        "host": "127.0.0.1",
        "port": int(config.get("POSTGRES_PORT", 5432)),
        "user": config["POSTGRES_USER"],
        "password": config["POSTGRES_PASSWORD"],
        "connect_timeout": 5,
    }
    with psycopg.connect(**connection_args, dbname="postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))

    def drop_database():
        with psycopg.connect(**connection_args, dbname="postgres", autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))

    stack.callback(drop_database)
    with psycopg.connect(**connection_args, dbname=name, autocommit=True) as db:
        db.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bucket = name.replace("_", "-")
    storage = Minio(
        "127.0.0.1:" + config.get("MINIO_API_PORT", "9000"),
        access_key=config["MINIO_ACCESS_KEY"],
        secret_key=config["MINIO_SECRET_KEY"],
        secure=False,
    )
    storage.make_bucket(bucket)

    def remove_bucket():
        for obj in storage.list_objects(bucket, recursive=True):
            storage.remove_object(bucket, obj.object_name)
        storage.remove_bucket(bucket)

    stack.callback(remove_bucket)
    print("Isolated PostgreSQL/pgvector database and MinIO bucket created", flush=True)
    return {
        "DATABASE_URL": URL.create(
            "postgresql+psycopg",
            username=connection_args["user"],
            password=connection_args["password"],
            host="127.0.0.1",
            port=connection_args["port"],
            database=name,
        ).render_as_string(hide_password=False),
        "NEO4J_ENABLED": "true",
        "NEO4J_URI": "bolt://127.0.0.1:" + config["NEO4J_BOLT_PORT"],
        "NEO4J_USER": config["NEO4J_USER"],
        "NEO4J_PASSWORD": config["NEO4J_PASSWORD"],
        "REDIS_ENABLED": "true",
        "REDIS_URL": "redis://127.0.0.1:" + config["REDIS_PORT"] + "/0",
        "MINIO_ENABLED": "true",
        "MINIO_ENDPOINT": "127.0.0.1:" + config["MINIO_API_PORT"],
        "MINIO_ACCESS_KEY": config["MINIO_ACCESS_KEY"],
        "MINIO_SECRET_KEY": config["MINIO_SECRET_KEY"],
        "MINIO_BUCKET": bucket,
    }


def start_local(stack, folder, infrastructure=None):
    for name, port in SERVICES.items():
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is occupied; refusing to test an existing service")
        cwd = ROOT / ("apps/api" if name == "api" else f"services/{name}-service")
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+pysqlite:///{folder / (name + '.db')}",
            "NEO4J_ENABLED": "false",
            "MINIO_ENABLED": "false",
            "REDIS_ENABLED": "false",
            "AUTH_REQUIRED": "false",
            "PROFILE_AUTH_ENABLED": "false",
            "DOCUMENT_SERVICE_ENABLED": "true",
            "SEED_DEMO_DATA": "false",
            "LLM_PROVIDER": "mock",
            "SHIPMENT_SERVICE_URL": f"http://127.0.0.1:{SERVICES['shipment']}",
            "DOCUMENT_SERVICE_URL": f"http://127.0.0.1:{SERVICES['document']}",
            "LOCAL_OBJECT_STORAGE_PATH": str(folder / "objects"),
            "DOCUMENT_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        }
        env.update(infrastructure or {})
        log = stack.enter_context((folder / f"{name}.log").open("w+"))
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=log,
        )

        def stop(child=process):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()

        stack.callback(stop)
        for _ in range(60):
            if process.poll() is not None:
                log.seek(0)
                raise RuntimeError(f"{name} failed to start: {log.read()}")
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
                response.raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise RuntimeError(f"{name} did not become ready")


def exercise(infrastructure=None):
    from domestic_smoke import exercise as domestic_exercise
    return domestic_exercise(SERVICES, os.environ.get("SMOKE_AUTH_TOKEN"))


def legacy_exercise(infrastructure=None):
    client = httpx.Client(
        timeout=30,
        headers={
            **(
                {"Authorization": f"Bearer {os.environ['SMOKE_AUTH_TOKEN']}"}
                if os.environ.get("SMOKE_AUTH_TOKEN")
                else {}
            ),
        },
    )

    def request(service, method, path, **kwargs):
        response = client.request(method, f"http://127.0.0.1:{SERVICES[service]}{path}", **kwargs)
        assert response.is_success, f"{method} {path}: {response.status_code} {response.text}"
        return response

    for name in SERVICES:
        assert request(name, "GET", "/health").json()["status"] == "ok"
        if name != "api":
            assert request(name, "GET", "/ready").json()["status"] == "ok"
    now = datetime.now(UTC)
    payload = {
        "shipment_reference": f"TT-AUDIT-{uuid.uuid4().hex[:10]}",
        "exporter_country": "India",
        "importer_country": "Germany",
        "transport_mode": "SEA",
        "planned_departure_at": now.isoformat(),
        "planned_arrival_at": (now + timedelta(days=21)).isoformat(),
        "consignments": [],
        "route_legs": [],
    }
    shipment = request("shipment", "POST", "/shipments", json=payload).json()
    shipment_id = shipment["id"]
    base = f"/shipments/{shipment_id}"
    try:
        for name, destination in [
            ("Lithium batteries", "Germany"),
            ("Consumer electronics", "UAE"),
        ]:
            request(
                "shipment",
                "POST",
                f"{base}/consignments",
                json={
                    "product_name": name,
                    "product_description": name,
                    "quantity": 120,
                    "declared_value": "18000.00",
                    "currency": "USD",
                    "country_of_origin": "India",
                    "destination_country": destination,
                },
            )
        for sequence, origin, destination in [(1, "India", "UAE"), (2, "UAE", "Germany")]:
            request(
                "shipment",
                "POST",
                f"{base}/route-legs",
                json={
                    "sequence_number": sequence,
                    "origin_country": origin,
                    "destination_country": destination,
                    "transport_mode": "SEA",
                    "carrier_name": "Audit",
                },
            )
        shipment = request("shipment", "GET", base).json()
        lithium, electronics = shipment["consignments"]
        events = [
            ("CREATED", "India", None),
            ("LOADED", "India", lithium["id"]),
            ("LOADED", "India", electronics["id"]),
            ("ARRIVED_AT_TRANSIT_PORT", "UAE", None),
            ("UNLOADED", "UAE", electronics["id"]),
        ]
        for index, (event_type, country, consignment_id) in enumerate(events):
            request(
                "shipment",
                "POST",
                f"{base}/events",
                json={
                    "event_type": event_type,
                    "location_country": country,
                    "consignment_id": consignment_id,
                    "occurred_at": (now + timedelta(minutes=index)).isoformat(),
                },
            )
        shipment = request("shipment", "GET", base).json()
        states = {c["id"]: c["customs_status"] for c in shipment["consignments"]}
        assert states[lithium["id"]] == "UAE_TRANSIT"
        assert states[electronics["id"]] == "UAE_IMPORT"
        assert len(request("shipment", "GET", f"{base}/timeline").json()["events"]) == 5
        assert request("shipment", "GET", f"{base}/graph").json()["edges"]
        if infrastructure:
            from neo4j import GraphDatabase

            with (
                GraphDatabase.driver(
                    infrastructure["NEO4J_URI"],
                    auth=(
                        infrastructure["NEO4J_USER"],
                        infrastructure["NEO4J_PASSWORD"],
                    ),
                ) as driver,
                driver.session() as graph,
            ):
                states = [
                    row["status"]
                    for row in graph.run(
                        "MATCH (:Shipment {id:$id})-[:CONTAINS]->(c:Consignment) "
                        "RETURN c.customsStatus AS status",
                        id=shipment_id,
                    )
                ]
                assert sorted(states) == ["UAE_IMPORT", "UAE_TRANSIT"]
            print("PASS: persisted Neo4j graph matches PostgreSQL consignment states", flush=True)
        print("PASS: shipment, consignments, route, split events and graph", flush=True)

        def upload(kind, consignment_id=None):
            content = (
                "Document Number: AUDIT-001\nDocument Date: 2026-09-08\n"
                "Product Name: Lithium batteries\nQuantity: 120\n"
                "Country of Origin: India\nDeclared Value: USD 18000.00\n"
            )
            document = request(
                "document",
                "POST",
                f"{base}/documents",
                data={"document_type": kind, "consignment_id": consignment_id or ""},
                files={"file": (f"{kind}.txt", content, "text/plain")},
            ).json()
            extracted = request("document", "POST", f"/documents/{document['id']}/extract").json()
            assert extracted["verification_status"] == "EXTRACTED"
            assert request("document", "GET", f"/documents/{document['id']}").json()[
                "document_number"
            ]
            return document["id"]

        for kind in [
            "commercial_invoice",
            "packing_list",
            "export_declaration",
            "import_declaration",
            "certificate_of_origin",
            "transit_declaration",
        ]:
            upload(kind)
        before = request("compliance", "POST", f"/compliance/evaluate/{shipment_id}").json()
        assert before["status"] == "CONDITIONALLY_COMPLIANT"
        question = request("compliance", "GET", f"{base}/questions").json()[0]
        assert "sealed onboard" in question["question"]
        answer = request(
            "compliance",
            "POST",
            f"{base}/questions/{question['question_id']}/answer",
            json={"answer": "Yes"},
        ).json()
        assert answer["answer"] == "yes"
        request("compliance", "POST", f"/consistency/check/{shipment_id}")
        print("PASS: compliance and highest-impact question through HTTP", flush=True)

        # Regulation publication is confined to the isolated local environment.
        if ARGS.local:
            regulation = request("compliance", "POST", "/regulations", json={}).json()
            request("compliance", "POST", f"/regulations/{regulation['id']}/publish-version")
            impacts = request(
                "compliance",
                "POST",
                "/regulations/impact-analysis",
                json={"regulation_ids": [regulation["id"]]},
            ).json()
            impact = next(
                x for x in impacts["impacted_shipments"] if x["shipment_id"] == shipment_id
            )
            assert impact["new_status"] == "NON_COMPLIANT"
            assert request(
                "document", "GET", f"/assessments/{impact['assessment']['id']}/evidence"
            ).json()
            routes = request("compliance", "POST", f"/optimizer/route-options/{shipment_id}").json()
            assert routes["recommended_route_id"] == "split-compliant-route"
            print("PASS: regulation publication, impact evidence and alternate route", flush=True)

        safety_id = upload("safety_certificate", lithium["id"])
        after = request("compliance", "POST", f"/compliance/evaluate/{shipment_id}").json()
        assert after["status"] == "COMPLIANT"
        if infrastructure:
            from redis import Redis

            with Redis.from_url(infrastructure["REDIS_URL"]) as redis:
                stored_job = redis.get(f"tradetwin:compliance:jobs:{after['job_id']}")
                assert json.loads(stored_job)["status"] == "COMPLETED"
            print("PASS: completed compliance job persisted in Redis", flush=True)
        evidence = request("document", "GET", f"/assessments/{after['id']}/evidence").json()
        assert any(row["document_id"] == safety_id for row in evidence)
        assert request("compliance", "GET", f"/compliance/assessments/{shipment_id}").json()
        print("PASS: upload, extraction, reevaluation and certificate provenance", flush=True)
        classification = request(
            "intelligence",
            "POST",
            "/intelligence/hs-classify",
            json={
                "product_name": "Lithium batteries",
                "product_description": "Rechargeable lithium batteries",
            },
        ).json()
        assert len(classification["recommendations"]) == 3
        request("intelligence", "POST", f"/intelligence/risk-score/{shipment_id}")
        assert request("intelligence", "GET", f"{base}/risk-assessment").json()["warning"]
        for fmt in ["html", "pdf"]:
            report = request("compliance", "GET", f"/reports/compliance/{shipment_id}?format={fmt}")
            assert report.content.startswith(b"%PDF" if fmt == "pdf" else b"<!doctype html>")
        assert request("compliance", "GET", f"/audit-logs?shipment_id={shipment_id}").json()
        print("PASS: HS classification, synthetic risk, HTML/PDF reports and audit", flush=True)
    finally:
        request("shipment", "DELETE", base)
        client.close()
    print("PASS: shipment deletion", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--port-offset", type=int, default=10000)
    parser.add_argument(
        "--browser", action="store_true", help="Run UI checks against localhost:3100"
    )
    parser.add_argument(
        "--infrastructure",
        action="store_true",
        help="Use isolated resources on the existing infrastructure containers",
    )
    parser.add_argument(
        "--serve", action="store_true", help="Keep isolated services alive for UI checks"
    )
    ARGS = parser.parse_args()
    if (ARGS.infrastructure or ARGS.browser) and not ARGS.local:
        parser.error("--infrastructure and --browser require --local")
    if ARGS.local:
        SERVICES = {name: port + ARGS.port_offset for name, port in SERVICES.items()}
    with ExitStack() as stack:
        if ARGS.local:
            folder = Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-audit-"))
            )
            infrastructure = infrastructure_environment(stack) if ARGS.infrastructure else None
            start_local(stack, folder, infrastructure)
            if ARGS.browser:

                def clean_browser_shipments():
                    # This service uses only the temporary audit database created above.
                    base = f"http://127.0.0.1:{SERVICES['shipment']}/shipments"
                    with httpx.Client(timeout=30) as client:
                        shipments = client.get(base)
                        shipments.raise_for_status()
                        for shipment in shipments.json():
                            client.delete(f"{base}/{shipment['id']}").raise_for_status()

                stack.callback(clean_browser_shipments)
        exercise(infrastructure if ARGS.local else None)
        if ARGS.browser:
            subprocess.run([sys.executable, str(ROOT / "scripts/browser-check.py")], check=True)
        if ARGS.serve:
            print("Local audit services ready for browser checks. Ctrl+C stops them.", flush=True)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
