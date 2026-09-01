# ruff: noqa: E402, I001

import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["DOCUMENT_SERVICE_ENABLED"] = "false"
os.environ["REDIS_ENABLED"] = "false"

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from tests.test_evaluator import (
    documents_without_battery_certificate,
    sample_events,
    sample_shipment,
)
from app.database import Base, SessionLocal, engine
from app.evaluator import load_rules
from app.optimizer import optimize_routes
from app import regulations
from app.regulations import demo_uae_transit_safety_rule
from app.schemas import ComplianceStatus, ImpactAnalysisRequest


def test_optimizer_rejects_current_uae_route_after_new_safety_rule() -> None:
    result = optimize_routes(
        sample_shipment(),
        sample_events(),
        documents_without_battery_certificate(),
        [*load_rules(), demo_uae_transit_safety_rule()],
    )

    current_route = next(option for option in result.options if option.route_id == "current-route")
    recommended = next(option for option in result.options if option.is_recommended)

    assert current_route.legal_status == "INVALID"
    assert current_route.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert "lithium_battery_safety_certificate" in current_route.missing_documents
    assert recommended.route_id == "split-compliant-route"
    assert recommended.compliance_status == ComplianceStatus.COMPLIANT


def test_regulation_impact_identifies_lithium_shipment(monkeypatch) -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        regulation = regulations.create_regulation_version(db)
        regulations.publish_regulation_version(db, regulation.id)

        monkeypatch.setattr(regulations, "list_shipments", lambda: [sample_shipment()])
        monkeypatch.setattr(
            regulations,
            "get_shipment_context",
            lambda shipment_id: (sample_shipment(), sample_events()),
        )
        monkeypatch.setattr(regulations, "get_uploaded_documents", lambda shipment_id: [])

        result = regulations.analyze_regulation_impact(
            db,
            ImpactAnalysisRequest(
                regulation_ids=[regulation.id],
                uploaded_documents=[
                    document.model_dump()
                    for document in documents_without_battery_certificate()
                ],
            ),
        )
    finally:
        db.close()

    assert result.analyzed_regulations[0].rule_id == "TT-UAE-LITHIUM-SAFETY-002"
    assert len(result.impacted_shipments) == 1
    impact = result.impacted_shipments[0]
    lithium_id = next(
        consignment["id"]
        for consignment in sample_shipment()["consignments"]
        if consignment["product_name"] == "Lithium batteries"
    )
    assert impact.previous_status == ComplianceStatus.CONDITIONALLY_COMPLIANT
    assert impact.new_status == ComplianceStatus.NON_COMPLIANT
    assert impact.affected_consignment_ids == [lithium_id]
    assert impact.route_recommendation is not None
    assert impact.route_recommendation.route_id == "split-compliant-route"
    assert "Upload the lithium battery safety certificate" in impact.corrective_action
