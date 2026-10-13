"""Internal opt-in simulation seed. No public reset, scan or release bypass."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

import httpx
from sqlalchemy import select
from tradetwin_security.document_worker import headers

from app.database import SessionLocal, engine
from app.operations import attachments
from app.operations.cli import Demo
from app.operations.demo import seed_demo
from app.operations.models import Attachment, Consignment
from app.operations.schemas import AttachmentUploadInput
from app.trades.migrate import migrate
from app.trades.models import Trade, now

from . import context, demo, evaluations, governance, templates
from .models import Binding, Pack
from .schemas_facts import EvaluationInput
from .schemas_rules import SourceInput


def real_storage(db, ctx, trade, cn, label, content, purpose):
    uploaded = attachments.begin(
        db,
        ctx,
        AttachmentUploadInput(
            trade_id=trade.id,
            consignment_id=cn.id if cn else None,
            purpose=purpose,
            original_name=label,
            content_type="application/pdf",
            size_bytes=len(content),
        ),
    )
    db.commit()  # The document service must see the authorized upload record.
    url = os.getenv("DOCUMENT_SERVICE_URL", "http://127.0.0.1:8013").rstrip("/")
    with httpx.Client(timeout=45) as client:
        response = client.post(
            f"{url}/internal/document-desk/import-generated-fixture",
            headers=headers(),
            json={
                "attachment_id": uploaded["id"],
                "user_id": ctx.user.id,
                "organization_id": ctx.org_id,
                "content_base64": base64.b64encode(content).decode(),
                "expected_sha256": hashlib.sha256(content).hexdigest(),
            },
        )
        response.raise_for_status()
        checked = response.json()
    if checked["security_state"] != "CLEAN":
        raise RuntimeError("Simulation source remains quarantined; configure/repair ClamAV.")
    row = db.get(Attachment, uploaded["id"])
    row.sha256, row.security_state, row.finalised_at = checked["sha256"], "CLEAN", now()
    db.flush()
    return row


def production_candidate(db, fx, source_folder):
    catalog = json.loads((source_folder / "catalog.json").read_text())
    author = demo.actor(db, fx, "seller-operations")
    source_ids = []
    trade = db.get(Trade, fx["trade_id"])
    for item in catalog["sources"]:
        content = (source_folder / item["file"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise RuntimeError("Source snapshot changed; review and repin its catalog hash.")
        asset = real_storage(db, author, trade, None, item["file"], content, "OTHER")
        source = governance.source(
            db,
            author,
            None,
            SourceInput(
                source_status=item.get("source_status", "UNKNOWN"),
                source_kind=item["kind"],
                issuer=item["issuer"],
                title=item["title"],
                official_url=item["url"],
                document_number=item.get("document_number"),
                retrieved_at=now(),
                snapshot_attachment_id=asset.id,
                source_sha256=asset.sha256,
                jurisdictions=["IN"],
                interpretation_note=item["interpretation_note"],
                source_origin="OFFICIAL_SNAPSHOT_PROVIDED",
            ),
        )
        source_ids.append(source["id"])
    # This never tests, reviews or publishes a production candidate on behalf of a human.
    draft = templates.candidate(source_ids, "PRODUCTION", "candidate-" + trade.id[:8])
    draft.limitations = [*draft.limitations, *catalog["limitations"]]
    candidate = governance.create_pack(db, author, None, draft)
    return candidate["id"]


def seed(
    sessions=SessionLocal,
    namespace="phase4",
    subjects=None,
    scenario="matching",
    source_folder=None,
):
    if os.getenv("DOCUMENT_DEMO_ENABLED", "false").lower() != "true":
        raise RuntimeError("DOCUMENT_DEMO_ENABLED=true is required in development only.")
    with sessions() as db:
        fx = seed_demo(db, subjects, namespace)
    harness = Demo(sessions, fx)
    with sessions() as db:
        existing = db.scalar(select(Consignment).where(Consignment.trade_id == fx["trade_id"]))
        consignment_id = existing.id if existing else None
    if consignment_id is None:
        cn = harness.allocate("100")
        harness.assignment(cn, 0)
        consignment_id = cn["id"]
    with sessions() as db:
        head = context.heads(db, db.get(Consignment, consignment_id))
        if not head or not head.current_binding_revision_id:
            demo.prepare(
                db,
                fx,
                consignment_id,
                real_storage,
                wrong_vehicle=scenario == "wrong-vehicle",
                omit_ewb=scenario == "missing-ewb",
            )
            db.commit()
        production = db.scalar(select(Pack.id).where(Pack.environment == "PRODUCTION"))
        if source_folder and production is None:
            production = production_candidate(db, fx, source_folder)
            db.commit()
        actor = demo.actor(db, fx, "seller-operations")
        actor.if_match = f'"{context.version(db, fx["trade_id"])}"'
        queued = evaluations.request(
            db,
            actor,
            consignment_id,
            EvaluationInput(
                action="PICKUP_CONFIRMED",
                expected_context_version=context.version(db, fx["trade_id"]),
            ),
        )
        db.commit()
        binding = db.get(
            Binding,
            context.heads(db, db.get(Consignment, consignment_id)).current_binding_revision_id,
        )
    return {
        **fx,
        "consignment_id": consignment_id,
        "evaluation_id": queued["evaluation_id"],
        "binding_id": binding.id,
        "production_candidate_id": production,
        "notice": "SIMULATION: synthetic signatures/status observations; encrypted real files. "
        "The production candidate is unpublished and cannot enable dispatch.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="phase4")
    parser.add_argument("--identity-map", type=Path)
    parser.add_argument("--source-folder", type=Path)
    parser.add_argument(
        "--scenario", choices=["matching", "missing-ewb", "wrong-vehicle"], default="matching"
    )
    args = parser.parse_args()
    migrate(engine)
    subjects = json.loads(args.identity_map.read_text()) if args.identity_map else None
    print(
        json.dumps(
            seed(
                namespace=args.namespace,
                subjects=subjects,
                scenario=args.scenario,
                source_folder=args.source_folder,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
