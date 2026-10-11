"""Exercise real HTTP service boundaries; --local uses isolated temporary SQLite stores."""

import argparse
import base64
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

import httpx
from dotenv import dotenv_values
from local_processes import stop_process

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

        stack.callback(stop_process, process)
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

    return domestic_exercise(SERVICES, os.environ.get("SMOKE_AUTH_TOKEN"), infrastructure)


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
    if not ARGS.local:
        parser.error("Use --local for isolated test data; add --infrastructure to test containers")
    if ARGS.local:
        SERVICES = {name: port + ARGS.port_offset for name, port in SERVICES.items()}
    with ExitStack() as stack:
        if ARGS.local:
            folder = Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="tradetwin-audit-"))
            )
            infrastructure = infrastructure_environment(stack) if ARGS.infrastructure else None
            start_local(stack, folder, infrastructure)

            def clean_test_shipments():
                # Only the temporary database above is queried; also remove its Neo4j projections.
                base = f"http://127.0.0.1:{SERVICES['shipment']}/shipments"
                with httpx.Client(timeout=30) as client:
                    shipments = client.get(base)
                    shipments.raise_for_status()
                    for shipment in shipments.json():
                        client.delete(f"{base}/{shipment['id']}").raise_for_status()

            stack.callback(clean_test_shipments)
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
