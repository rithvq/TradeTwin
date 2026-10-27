"""Registered SIMULATION actions. Use the same commands and guards as the product."""

from datetime import timedelta

from sqlalchemy import select

from app.compliance import demo as release
from app.compliance.clock import instant
from app.corridor import events, governance, sources
from app.corridor import schemas as cs
from app.freight import commitments
from app.freight.models import Candidate, Quote, Run
from app.freight.schemas import CarrierDecision, SelectionDecision, SelectionInput
from app.operations import movement
from app.operations.access import fail
from app.operations.models import Consignment
from app.operations.schemas import ShipmentEventInput
from app.trades.models import uid


def accept(db, fx, quote_name):
    cn = db.get(Consignment, fx["consignment_id"])
    run = db.get(Run, fx["run_id"])
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.run_id == run.id, Candidate.quote_revision_id == fx["quotes"][quote_name]
        )
    )
    if not candidate:
        fail("DEMO_CANDIDATE_MISSING", "The current comparison has no matching offer.")
    quote = db.get(Quote, candidate.quote_revision_id)
    preparer, reviewer, carrier = [
        release.actor(db, fx, r)
        for r in ["seller-operations", "seller-approver", "carrier-dispatcher"]
    ]
    preparer.if_match = f'"{cn.row_version}"'
    proposal = commitments.propose(
        db,
        preparer,
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
            reason="Independent simulation payer approval",
        ),
        "PAYER",
    )
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
            reason="Simulation carrier acceptance of exact offer and resources",
        ),
    )


def move(db, fx, kind):
    cn = db.get(Consignment, fx["consignment_id"])
    guarded, payload = {}, {}
    if kind in {"PICKUP_CONFIRMED", "DEPARTED"}:
        guarded["dispatch_authorization_id"] = fx["authorizations"][kind]
    if kind == "PICKUP_CONFIRMED":
        guarded["loading_manifest_revision_id"] = fx["phase4"]["manifest_id"]
        from app.operations.quantities import items

        payload = {
            "items": [
                {
                    "consignment_item_id": i.id,
                    "loaded_quantity": str(i.allocated_quantity),
                    "uqc": i.uqc,
                }
                for i in items(db, cn.id)
            ],
            "actual_gross_weight_kg": "400",
            "actual_package_count": 4,
        }
    return movement.event(
        db,
        release.actor(db, fx, "driver-one"),
        cn.id,
        ShipmentEventInput(
            client_event_id=uid(),
            assignment_id=cn.active_assignment_id,
            event_type=kind,
            occurred_at=instant(db),
            payload=payload,
            notes="SIMULATION registered demo event; not verified vehicle telemetry",
            **guarded,
        ),
    )


def restriction(db, fx):
    author, reviewer = [release.actor(db, fx, r) for r in ["seller-operations", "seller-approver"]]
    at = instant(db)
    source = sources.create(
        db,
        author,
        None,
        cs.ConnectionInput(
            provider_code="SIMULATION",
            environment="SIMULATION",
            source_kind="SIMULATION",
            documented_endpoint_reference="Retained synthetic advisory; no live road closure claim",
            endpoint_contract_version="SIMULATION_V1",
            approved_https_hosts=[],
            covered_state_codes=["29"],
            covered_event_kinds=["ROAD_CLOSURE"],
            maximum_item_age_seconds=86400,
            retention_policy="PERMITTED_ARCHIVE",
            source_item_storage_allowed=True,
            attribution_text="TradeTwin SIMULATION",
        ),
    )
    author.if_match = source["etag"]
    sources.status(
        db,
        author,
        source["id"],
        cs.ConnectionStatus(status="CONFIGURED", reason="Registered synthetic source"),
    )
    item = sources.manual(
        db,
        author,
        None,
        cs.SourceInput(
            source_connection_id=source["id"],
            provider_item_key=uid(),
            source_issued_at=at,
            retrieved_at=at,
            source_reference="SIMULATION retained closure advisory",
            payload_sha256="a" * 64,
            mime_type="application/json",
        ),
    )
    candidate = db.scalar(
        select(Candidate).where(
            Candidate.run_id == fx["run_id"], Candidate.quote_revision_id == fx["quotes"]["A"]
        )
    )
    route = candidate.candidate_json["scenarios"]["BASE"]["route"]
    head = events.incident(
        db,
        author,
        None,
        cs.IncidentInput(
            environment="SIMULATION",
            visibility="CONSIGNMENT_ONLY",
            consignment_id=fx["consignment_id"],
        ),
    )
    author.if_match = head["etag"]
    row = events.create(
        db,
        author,
        head["id"],
        cs.EventInput(
            source_item_id=item["id"],
            event_kind="ROAD_CLOSURE",
            headline="Simulated direct-road closure",
            summary="An independently reviewed synthetic closure excludes the direct route.",
            source_sender="TradeTwin simulation",
            source_identifier=uid(),
            source_sent_at=at,
            severity="SEVERE",
            assessed_effective_from=at,
            assessed_effective_until=at + timedelta(days=1),
            operational_review_due_at=at + timedelta(hours=6),
            time_interpretation="UTC simulation",
            geography=cs.Geography(
                geometry_kind="ROAD_EDGE_SET",
                dataset_revision_id=route["dataset_revision_id"],
                edge_keys=[route["ordered_edge_keys"][0]],
                state_codes=["29"],
                direction="BOTH",
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
        cs.PolicyInput(
            environment="SIMULATION",
            policy_code="APP_DEMO_" + uid(),
            event_kinds=["ROAD_CLOSURE"],
            state_codes=["29"],
            source_kinds=["SIMULATION"],
            effect="EXCLUDE_EDGE",
            minimum_precision="EXACT_EDGE",
            maximum_source_age_seconds=86400,
            missing_coverage_action="SHOW_LIMITATION",
            release_condition="REOPENING_EVIDENCE",
            source_references=["Synthetic simulation policy"],
            effective_from=at,
            effective_until=at + timedelta(days=2),
        ),
    )
    governance.decide(
        db,
        reviewer,
        policy["id"],
        cs.Review(
            content_hash=policy["content_hash"],
            decision="APPROVE",
            reason="Independent simulation policy review",
        ),
    )
    governance.decide(
        db,
        reviewer,
        policy["id"],
        cs.Exact(content_hash=policy["content_hash"], reason="Publish simulation policy"),
        publish=True,
    )
    events.review(
        db,
        reviewer,
        row["id"],
        cs.Review(
            content_hash=row["content_hash"],
            decision="APPROVE",
            reason="Independent simulation advisory review",
        ),
    )
    events.publish(
        db,
        reviewer,
        row["id"],
        cs.Exact(
            content_hash=row["content_hash"],
            reason="Publish consignment-scoped simulation advisory",
        ),
    )
    return row["id"]
