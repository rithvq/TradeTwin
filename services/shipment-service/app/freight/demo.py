"""Isolated Phase 4 synthetic trade plus retained Phase 5 offers. No live credentials."""

from datetime import timedelta

from sqlalchemy import select

from app.compliance import demo as release_demo
from app.compliance.clock import instant
from app.operations.cli import Demo
from app.operations.demo import ROLES, seed_demo
from app.operations.models import Assignment, Consignment, Vehicle
from app.trades import profiles
from app.trades.models import Trade, uid
from app.trades.schemas import MembershipChange
from app.trades.terms import digest

from . import offers, routing, runs
from .models import Quote, QuoteHead
from .schemas import (
    DatasetInput,
    GenerateInput,
    HashCommand,
    LocationInput,
    ProfileInput,
    QuoteInput,
    RFQInput,
    RunInput,
)


def seed(sessions, namespace="phase4-freight"):
    with sessions() as db:
        fx = seed_demo(db, namespace=namespace)
        for role, added in {
            "seller-operations": ["TRADE_PLANNER", "ROUTING_DATA_PREPARER"],
            "seller-approver": [
                "FREIGHT_PROCUREMENT_APPROVER",
                "TRANSPORT_PLAN_APPROVER",
                "ROUTING_DATA_STEWARD",
            ],
            "seller-finance": ["FREIGHT_COST_PREPARER"],
        }.items():
            ctx = release_demo.actor(db, fx, "seller-operations")
            profiles.change_membership(
                db,
                ctx,
                fx["organizations"]["seller"],
                MembershipChange(user_id=fx["users"][role], capabilities=[*ROLES[role][1], *added]),
            )
        db.commit()
    harness = Demo(sessions, fx)
    cn = harness.allocate("100")
    assignment = harness.assignment(cn, 0)
    with sessions() as db:
        prepared = release_demo.prepare(db, fx, cn["id"])
        db.commit()
        values = prepare(db, fx, cn["id"])
        db.commit()
    return {
        **fx,
        **values,
        "consignment_id": cn["id"],
        "original_assignment_id": assignment["id"],
        "phase4": prepared,
    }


def refresh_phase4(db, fx, ident, immediate=False):
    """Explicit independent simulation review, reusing the original issued invoice."""
    from copy import deepcopy

    from app.compliance import bindings, context, facts
    from app.compliance.models import Binding, Fact, Manifest, TransportEvidence
    from app.compliance.schemas_facts import (
        BindingPrepare,
        DeclarationReview,
        EvidenceBindings,
        FactPrepare,
        Facts,
        LoadingManifest,
        ManifestPrepare,
        TransportInput,
    )

    cn = db.get(Consignment, ident)
    if cn.execution_mode != "SIMULATION":
        raise ValueError("Simulation review cannot affect production")
    head = context.heads(db, cn)
    old_binding = db.get(Binding, head.current_binding_revision_id)
    old_fact = db.get(Fact, head.current_fact_revision_id)
    old_manifest = db.get(Manifest, head.current_loading_manifest_revision_id)
    planner, reviewer, carrier, carrier_reviewer = [
        release_demo.actor(db, fx, r)
        for r in ["seller-operations", "seller-approver", "carrier-dispatcher", "carrier-reviewer"]
    ]
    from .commitments import phase4_dependency

    route = phase4_dependency(db, cn)["plan"]
    value = deepcopy(old_fact.facts_json)
    value = {k: v for k, v in value.items() if k in Facts.model_fields and k != "field_provenance"}
    value.update(
        declared_transit_state_codes=route["state_sequence"][1:-1],
        requested_pickup_at=instant(db).isoformat() if immediate else route["planned_pickup_at"],
        requested_departure_at=instant(db).isoformat()
        if immediate
        else route["planned_departure_at"],
        expected_arrival_at=route["estimated_arrival_at"],
        corridor_declaration_basis="SUPPORTED_ROUTE_RECORD",
    )
    planner.if_match = f'"{context.version(db, cn.trade_id)}"'
    prepared = facts.prepare(
        db,
        planner,
        cn.id,
        FactPrepare(
            expected_context_version=context.version(db, cn.trade_id),
            facts=value,
            submit_for_review=True,
        ),
    )
    facts.review(
        db,
        reviewer,
        prepared["id"],
        DeclarationReview(
            decision="APPROVE_DECLARATION", reason="Independent committed-plan simulation review"
        ),
    )
    planner.if_match = f'"{context.version(db, cn.trade_id)}"'
    manifest = facts.manifest(
        db,
        planner,
        cn.id,
        ManifestPrepare(
            expected_context_version=context.version(db, cn.trade_id),
            manifest={
                k: v
                for k, v in old_manifest.manifest_json.items()
                if k in LoadingManifest.model_fields
            },
        ),
    )
    evidence, parent = [], None
    originals = [
        db.get(TransportEvidence, i)
        for i in old_binding.binding_json["transport_evidence_revision_ids"]
    ]
    originals.sort(key=lambda e: e.evidence_type == "PERMIT_AUTHORISATION")
    for old in originals:
        payload = deepcopy(old.evidence_json)
        payload.update(
            assignment_id=cn.active_assignment_id,
            subject_type=old.subject_type,
            subject_id=old.subject_id,
            evidence_type=old.evidence_type,
            document_version_id=old.document_version_id,
            reviewed_fact_revision_id=old.reviewed_fact_revision_id,
            parent_permit_evidence_revision_id=parent
            if old.evidence_type == "PERMIT_AUTHORISATION"
            else None,
        )
        payload = {k: v for k, v in payload.items() if k in TransportInput.model_fields}
        row = facts.transport(db, carrier, cn.id, TransportInput.model_validate(payload))
        facts.transport_review(
            db,
            carrier_reviewer,
            row["id"],
            DeclarationReview(
                decision="APPROVE_DECLARATION",
                reason="Independent actual assignment evidence rebind",
            ),
        )
        evidence.append(row["id"])
        if old.evidence_type == "GOODS_PERMIT":
            parent = row["id"]
    value = deepcopy(old_binding.binding_json)
    value = {k: v for k, v in value.items() if k in EvidenceBindings.model_fields}
    value.update(
        compliance_fact_revision_id=prepared["id"],
        loading_manifest_revision_id=manifest["id"],
        transport_evidence_revision_ids=evidence,
    )
    planner.if_match = f'"{context.version(db, cn.trade_id)}"'
    return bindings.prepare(
        db,
        planner,
        cn.id,
        BindingPrepare(expected_context_version=context.version(db, cn.trade_id), bindings=value),
    )


def prepare(db, fx, ident, modern=False):
    cn = db.get(Consignment, ident)
    trade = db.get(Trade, cn.trade_id)
    if trade.execution_mode != "SIMULATION":
        raise ValueError("Phase 5 fixtures cannot modify production")
    planner, steward, carrier = [
        release_demo.actor(db, fx, r)
        for r in ["seller-operations", "seller-approver", "carrier-dispatcher"]
    ]
    at = instant(db)
    for role, lat, lon in [("PICKUP", "12.9716", "77.5946"), ("DROP", "13.0827", "80.2707")]:
        planner.if_match = f'"{cn.row_version}"'
        address = cn.pickup_address_snapshot if role == "PICKUP" else cn.delivery_address_snapshot
        routing.location(
            db,
            planner,
            cn.id,
            LocationInput(
                address_role=role,
                accepted_address_hash=digest(address),
                latitude=lat,
                longitude=lon,
                position_source="SIMULATION",
                precision="CONFIRMED_LOADING_GATE",
                state_code=address["state_code"],
                state_coordinate_conflict_resolved=True,
                note="Synthetic loading gate, not surveyed geography",
            ),
        )
    vehicle = db.get(Vehicle, fx["vehicles"][0])
    active = db.get(Assignment, cn.active_assignment_id)
    from app.compliance.models import TransportEvidence

    evidence_ids = list(
        db.scalars(select(TransportEvidence.id).where(TransportEvidence.assignment_id == active.id))
    )
    carrier.if_match = f'"{vehicle.row_version}"'
    profile = routing.profile(
        db,
        carrier,
        vehicle.id,
        ProfileInput(
            combined_tare_weight_kg="4000",
            maximum_authorised_combined_weight_kg="12000",
            overall_height_mm=3500,
            overall_width_mm=2400,
            overall_length_mm=8000,
            axle_count=2,
            maximum_actual_axle_load_kg="2500",
            toll_vehicle_class_code="SIM_TRUCK",
            speed_cap_kph=80,
            supported_cargo_profile_codes=["ORDINARY_GOODS"],
        ),
    )
    nodes = [
        {
            "node_key": "pickup",
            "latitude": "12.9716",
            "longitude": "77.5946",
            "state_code": "29",
            "node_kind": "PICKUP_ACCESS",
        },
        {
            "node_key": "direct",
            "latitude": "12.8",
            "longitude": "78.3",
            "state_code": "29",
            "node_kind": "JUNCTION",
        },
        {
            "node_key": "fast",
            "latitude": "12.9",
            "longitude": "78.5",
            "state_code": "29",
            "node_kind": "JUNCTION",
        },
        {
            "node_key": "detour",
            "latitude": "13.5",
            "longitude": "78.7",
            "state_code": "37" if modern else "28",
            "node_kind": "JUNCTION",
        },
        {
            "node_key": "drop",
            "latitude": "13.0827",
            "longitude": "80.2707",
            "state_code": "33",
            "node_kind": "DROP_ACCESS",
        },
    ]
    edges = []
    for code, distance, seconds, states in [
        ("direct", 360000, 21600, ["29", "33"]),
        ("fast", 400000, 18000, ["29", "33"]),
        ("detour", 480000, 28800, ["29", "37" if modern else "28", "33"]),
    ]:
        for index, (origin, destination) in enumerate([("pickup", code), (code, "drop")]):
            edges.append(
                {
                    "edge_key": code + str(index),
                    "from_node_key": origin,
                    "to_node_key": destination,
                    "directed": True,
                    "distance_meters": distance // 2,
                    "estimated_driving_seconds": seconds // 2,
                    "ordered_state_sequence": ["29"] if index == 0 else states,
                    "allowed_vehicle_profile_codes": ["ORDINARY_GOODS"],
                    "assessment_coverage": {
                        k: "ASSESSED_UNRESTRICTED"
                        for k in ["height", "width", "length", "loaded_weight", "axle_load"]
                    },
                }
            )
    data = routing.dataset(
        db,
        planner,
        DatasetInput(
            dataset_code="SYNTHETIC_" + cn.id,
            version="1",
            source_kind="SIMULATION_FIXTURE",
            source_reference="Phase 5 retained synthetic fixture; not highway measurements",
            supported_state_codes=["29", "37" if modern else "28", "33"],
            supported_vehicle_profile_codes=["ORDINARY_GOODS"],
            observed_at=at,
            valid_from=at - timedelta(days=1),
            valid_until=at + timedelta(days=60),
            attribution_text="TradeTwin simulation",
            license_reference="Internally authored fixture",
            retention_policy="PERMITTED_ARCHIVE",
            export_allowed=True,
            limitations=[
                "SIMULATION geography, restrictions, prices and timing. Not highway measurements."
                if modern
                else "SIMULATION geography, restrictions, prices and timing. State 28 is an "
                "artificial fixture corridor label, not a current GST state code."
            ],
            nodes=nodes,
            edges=edges,
        ),
        mode="SIMULATION",
    )
    for action in ["REVIEW_APPROVED", "PUBLISHED"]:
        routing.dataset_event(
            db,
            steward,
            data["id"],
            HashCommand(
                content_hash=data["content_hash"], reason="Independent synthetic dataset inspection"
            ),
            action,
        )
    base = runs.base_context(db, trade, cn)
    generated = routing.materialize(
        db,
        planner,
        cn.id,
        GenerateInput(
            pickup_location_revision_id=base["pickup_location_revision_id"],
            drop_location_revision_id=base["drop_location_revision_id"],
            vehicle_profile_revision_id=profile["id"],
            departure_at=at + timedelta(minutes=30),
            dataset_revision_id_or_provider_connection_id=data["id"],
            objective="TIME",
        ),
    )
    routes = {t["template_json"]["ordered_node_keys"][1]: t["id"] for t in generated["templates"]}
    planner.if_match = f'"{cn.row_version}"'
    rfq = offers.create_rfq(
        db,
        planner,
        cn.id,
        RFQInput(
            pickup_location_revision_id=base["pickup_location_revision_id"],
            drop_location_revision_id=base["drop_location_revision_id"],
            requested_route_template_revision_ids=list(routes.values()),
            requested_pickup_window_start=at,
            requested_pickup_window_end=at + timedelta(hours=4),
            required_arrival_by=at + timedelta(hours=20),
            invited_carrier_organisation_ids=[fx["organizations"]["carrier"]],
            response_deadline=at + timedelta(hours=3),
            service_requirement_codes=["TOLL", "FUEL_SURCHARGE", "LOADING"],
            request_note="SIMULATION ONLY",
        ),
    )
    planner.if_match = rfq["etag"]
    offers.publish(db, planner, rfq["id"], HashCommand(content_hash=rfq["content_hash"]))
    quotes = {}
    for name, route, net, tax in [
        ("A", "direct", "1800000", "90000"),
        ("B", "fast", "2100000", "105000"),
        ("C", "detour", "1600000", "80000"),
        ("D", "direct", "1500000", "75000"),
    ]:
        quote = offers.create_quote(
            db,
            carrier,
            rfq["id"],
            QuoteInput(
                route_template_revision_id=routes[route],
                vehicle_id=vehicle.id,
                routing_vehicle_profile_revision_id=profile["id"],
                driver_user_id=fx["users"]["driver-one"],
                transport_evidence_revision_ids=evidence_ids,
                offered_pickup_window_start=at,
                offered_pickup_window_end=at + timedelta(hours=4),
                offered_delivery_window_start=at,
                offered_delivery_window_end=at + timedelta(hours=20),
                booking_window_start=at - timedelta(hours=1),
                booking_window_end=at + timedelta(hours=22),
                delivery_terms="Estimated synthetic timing, not a guarantee",
                offer_kind="FIRM_OFFER",
                charge_components=[
                    {
                        "component_id": uid(),
                        "component_code": "BASE_FREIGHT",
                        "label": "Synthetic fixed freight " + name,
                        "amount_minor": net,
                    }
                ],
                carrier_charged_tax_minor=tax,
                tax_treatment="DECLARED_SUPPLIER_CHARGED",
                tax_note="Fixture declaration, not legal freight-rate guidance",
                service_coverage=[
                    {
                        "category_code": c,
                        "coverage": "EXCLUDED_PAYER_COST"
                        if name == "D" and c == "LOADING"
                        else "INCLUDED_IN_QUOTED_PRICE",
                        "explanation": "Explicit fixture coverage",
                    }
                    for c in ["TOLL", "FUEL_SURCHARGE", "LOADING"]
                ],
                contingent_charge_terms=[
                    {
                        "code": code,
                        "free_minutes": 30,
                        "billing_increment_minutes": 15,
                        "charge_per_increment_gross_minor": "25000",
                        "maximum_charge_gross_minor": "200000",
                        "applicability_note": "Synthetic gross waiting charge",
                    }
                    for code in ["ORIGIN_WAIT", "DESTINATION_WAIT"]
                ],
                cancellation_terms="Bilateral pre-pickup cancellation; no automatic payment/refund",
                valid_from=at - timedelta(minutes=1),
                accept_by=at + timedelta(hours=3),
                source_mode="SIMULATION",
                carrier_offer_reference=name,
            ),
        )
        head = db.get(QuoteHead, db.get(Quote, quote["id"]).quote_head_id)
        carrier.if_match = f'"{head.row_version}"'
        offers.quote_event(
            db, carrier, quote["id"], HashCommand(content_hash=quote["content_hash"]), "SUBMITTED"
        )
        quotes[name] = quote["id"]
    base = runs.base_context(db, trade, cn)
    planner.if_match = f'"{base["compliance_context_version"]}"'
    request = RunInput(
        expected_context_version=base["compliance_context_version"],
        planning_intent={
            "intended_pickup_at": at,
            "intended_departure_at": at + timedelta(minutes=30),
            "planned_stop_seconds": 1800,
        },
        quote_revision_ids=list(quotes.values()),
        route_template_revision_ids=list(routes.values()),
        scenarios=[
            {
                "scenario_code": "EXTRA_WAIT",
                "label": "Origin wait +46 minutes",
                "delay_placement": "ORIGIN_BEFORE_DEPARTURE",
                "additional_wait_minutes": 46,
                "assumption_origin": "SIMULATION",
            }
        ],
    )
    run = runs.request(db, planner, cn.id, request)
    return {
        "rfq_id": rfq["id"],
        "quotes": quotes,
        "run_id": run["run_id"],
        "demo_as_of": at.isoformat(),
        "profile_revision_id": profile["id"],
        "routes": routes,
        "run_request": request.model_dump(mode="json"),
    }
