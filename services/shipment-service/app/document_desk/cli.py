"""Opt-in development fixtures; no production resets or malware-scan bypass."""

import argparse
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
from app.operations.demo import ROLES, seed_demo
from app.operations.models import Attachment, Consignment
from app.operations.schemas import AttachmentUploadInput
from app.trades import profiles
from app.trades.migrate import migrate
from app.trades.models import Trade, User, now, uid
from app.trades.schemas import MembershipChange
from app.trades.transactions import Context

from . import register, schemas
from .models import Document, TrustedKey

FIXTURES = {
    "invoice.pdf": "TAX_INVOICE",
    "scanned-invoice.png": "TAX_INVOICE",
    "packing-list.pdf": "PACKING_LIST",
    "eway-copy.pdf": "EWAY_BILL_COPY",
    "lr-gr.pdf": "LR_GR",
    "signed-payload.json": "SIGNED_EINVOICE_JSON",
    "payment-evidence.pdf": "PAYMENT_EVIDENCE",
    "hostile-content.pdf": "OTHER",
    "mismatched-invoice.pdf": "TAX_INVOICE",
}


def seed(sessions=SessionLocal, namespace="phase3", subjects=None):
    if os.getenv("DOCUMENT_DEMO_ENABLED", "false").lower() != "true":
        raise RuntimeError("Set DOCUMENT_DEMO_ENABLED=true in development only.")
    folder = Path(os.getenv("DOCUMENT_FIXTURE_DIRECTORY", "/app/data/fixtures/document-desk"))
    with sessions() as db:
        fx = seed_demo(db, subjects, namespace)
        for role, extra in (
            ("seller-operations", "SELLER_DOCUMENT_REVIEWER"),
            ("buyer-receiver", "BUYER_DOCUMENT_REVIEWER"),
        ):
            side, roles = ROLES[role]
            profiles.change_membership(
                db,
                Context(db.get(User, fx["users"][role]), fx["organizations"][side], uid()),
                fx["organizations"][side],
                MembershipChange(user_id=fx["users"][role], capabilities=[*roles, extra]),
            )
        db.commit()
    demo = Demo(sessions, fx)
    with sessions() as db:
        has_schedule = bool(db.get(Trade, fx["trade_id"]).active_payment_schedule_id)
    if not has_schedule:
        demo.schedule()
    with sessions() as db:
        cn_ids = list(
            db.scalars(select(Consignment.id).where(Consignment.trade_id == fx["trade_id"]))
        )
    if not cn_ids:
        for index, quantity in enumerate(("40", "60")):
            cn = demo.allocate(quantity)
            demo.assignment(cn, index)
            cn_ids.append(cn["id"])
    with sessions() as db:
        public = (folder / "simulation-public.pem").read_text()
        kid = "PH3_SIMULATION_ONLY"
        if not db.scalar(select(TrustedKey).where(TrustedKey.key_identifier == kid)):
            from cryptography.hazmat.primitives import serialization

            serialization.load_pem_public_key(public.encode())
            fingerprint = hashlib.sha256(public.encode()).hexdigest()
            db.add(
                TrustedKey(
                    issuer="TradeTwin synthetic fixture",
                    key_purpose="IRP_SIGNATURE",
                    provider_environment="SIMULATION",
                    key_identifier=kid,
                    key_fingerprint=fingerprint,
                    algorithm="RS256",
                    public_key_reference=public,
                    official_source_url="https://example.invalid/simulation-only",
                    registry_policy_version="PH3_SIMULATION_V1",
                )
            )
        db.commit()
    documents = {}
    url = os.getenv("DOCUMENT_SERVICE_URL", "http://127.0.0.1:8013").rstrip("/")
    for name, kind in FIXTURES.items():
        with sessions() as db:
            previous = db.scalar(
                select(Document).where(Document.trade_id == fx["trade_id"], Document.label == name)
            )
            if previous:
                documents[name] = previous.id
                continue
            content = (folder / name).read_bytes()
            role = "seller-finance" if kind == "PAYMENT_EVIDENCE" else "seller-operations"
            ctx = Context(db.get(User, fx["users"][role]), fx["organizations"]["seller"], uid())
            mime = (
                "image/png"
                if name.endswith(".png")
                else "application/json"
                if name.endswith(".json")
                else "application/pdf"
            )
            purpose = (
                "PAYMENT"
                if kind == "PAYMENT_EVIDENCE"
                else "DOCUMENT_FINANCIAL"
                if kind in {"TAX_INVOICE", "SIGNED_EINVOICE_JSON"}
                else "DOCUMENT_OPERATIONAL"
            )
            uploaded = attachments.begin(
                db,
                ctx,
                AttachmentUploadInput(
                    trade_id=fx["trade_id"],
                    purpose=purpose,
                    original_name=name,
                    content_type=mime,
                    size_bytes=len(content),
                ),
            )
            db.commit()
            user_id = ctx.user.id
        with httpx.Client(timeout=40) as client:
            response = client.post(
                f"{url}/internal/document-desk/import-fixture",
                headers=headers(),
                json={
                    "attachment_id": uploaded["id"],
                    "user_id": user_id,
                    "organization_id": fx["organizations"]["seller"],
                    "fixture_name": name,
                },
            )
            response.raise_for_status()
            checked = response.json()
        if checked["security_state"] != "CLEAN":
            raise RuntimeError(
                f"{name}: scanner returned {checked['security_state']}; "
                "start/repair ClamAV before seeding."
            )
        with sessions() as db:
            ctx = Context(db.get(User, user_id), fx["organizations"]["seller"], uid())
            row = db.get(Attachment, uploaded["id"])
            row.sha256, row.security_state, row.finalised_at = (
                checked["sha256"],
                checked["security_state"],
                now(),
            )
            doc = register.create(
                db,
                ctx,
                fx["trade_id"],
                schemas.Registration(
                    trade_id=fx["trade_id"],
                    document_type=kind,
                    label=name,
                    primary_attachment_id=row.id,
                    visibility="OWNER_ONLY",
                ),
            )
            documents[name] = doc["id"]
            db.commit()
    return {
        **fx,
        "consignments": cn_ids,
        "documents": documents,
        "notice": "SIMULATION only. Review and mappings require explicit human actions. "
        "No government/bank credentials used.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="phase3")
    parser.add_argument(
        "--reset", action="store_true", help="Creates a new namespace; preserves prior evidence."
    )
    parser.add_argument("--identity-map", type=Path)
    args = parser.parse_args()
    migrate(engine)
    namespace = f"{args.namespace}-{uid()[:8]}" if args.reset else args.namespace
    subjects = json.loads(args.identity_map.read_text()) if args.identity_map else None
    print(json.dumps(seed(namespace=namespace, subjects=subjects), indent=2))


if __name__ == "__main__":
    main()
