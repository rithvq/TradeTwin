"""Retained road topology, explicit restriction coverage and immutable routing inputs."""

from decimal import Decimal
from itertools import islice

import networkx as nx
from sqlalchemy import func, select

from app.compliance.clock import aware, instant
from app.compliance.ledger import independent
from app.operations.access import aligned, before_pickup, exists, fail, match
from app.operations.ledger import record, touch, view
from app.operations.models import Vehicle
from app.trades.access import require
from app.trades.context_locks import bump_context, registry_lock
from app.trades.terms import digest

from .access import base_context, planning
from .models import Dataset, DatasetEvent, Location, LocationHead, Profile, Template


def latest_number(db, model, *where):
    return (db.scalar(select(func.max(model.revision_number)).where(*where)) or 0) + 1


def location(db, ctx, ident, payload):
    trade, cn = planning(db, ctx, ident, "tradetwin.plan.prepare", True)
    match(ctx, cn)
    before_pickup(cn)
    aligned(cn)
    address = (
        cn.pickup_address_snapshot
        if payload.address_role == "PICKUP"
        else cn.delivery_address_snapshot
    )
    if (
        payload.accepted_address_hash != digest(address)
        or payload.state_code != address["state_code"]
    ):
        fail(
            "ROUTING_INPUT_MISSING",
            "Pin must refer to the accepted address and state; "
            "use existing address amendment workflows.",
        )
    if payload.position_source == "SIMULATION" and trade.execution_mode != "SIMULATION":
        fail("MODE_MISMATCH", "Synthetic coordinates cannot be used for production.")
    if payload.position_source == "LICENSED_GEOCODER":
        fail(
            "PROVIDER_NOT_CONFIGURED",
            "No approved geocoder connection is configured; confirm a user pin.",
        )
    value = {
        **payload.model_dump(mode="json"),
        "execution_mode": trade.execution_mode,
        "confirmed_by_user_id": ctx.user.id,
        "confirmed_at": instant(db).isoformat(),
        "limitations": ["User confirmation is not independent boundary verification."],
    }
    row = Location(
        consignment_id=cn.id,
        address_role=payload.address_role,
        revision_number=latest_number(
            db,
            Location,
            Location.consignment_id == cn.id,
            Location.address_role == payload.address_role,
        ),
        accepted_address_hash=payload.accepted_address_hash,
        latitude=payload.latitude,
        longitude=payload.longitude,
        precision=payload.precision,
        state_code=payload.state_code,
        location_json=value,
        content_hash=digest(value),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    head = db.scalar(select(LocationHead).where(LocationHead.consignment_id == cn.id))
    if not head:
        head = LocationHead(consignment_id=cn.id, created_by=ctx.user.id)
        db.add(head)
    setattr(
        head,
        "pickup_location_revision_id"
        if payload.address_role == "PICKUP"
        else "drop_location_revision_id",
        row.id,
    )
    touch(cn)
    bump_context(db, trade.id, "ROUTING_LOCATION_CHANGED")
    record(db, ctx, "ROUTING_LOCATION_CONFIRMED", row, trade, cn)
    return view(row)


def profile(db, ctx, ident, payload):
    registry_lock(db, exclusive=True)
    vehicle = exists(db, Vehicle, ident)
    if vehicle.carrier_organization_id != ctx.org_id:
        fail("NOT_FOUND", "Vehicle not found.", status=404)
    require(db, ctx.user, ctx.org_id, "vehicle.manage")
    match(ctx, vehicle)
    if not vehicle.active:
        fail("RESOURCE_UNAVAILABLE", "Vehicle is inactive.")
    from app.compliance.models import TransportEvidence
    from app.document_desk import access as docs

    for ident in payload.source_document_version_ids:
        _, doc, _ = docs.version(db, ctx, ident)
        if doc.owner_organization_id != ctx.org_id:
            fail("NOT_FOUND", "Owned transport source not found.", status=404)
    for ident in payload.transport_evidence_revision_ids:
        evidence = exists(db, TransportEvidence, ident)
        if evidence.owner_organisation_id != ctx.org_id or evidence.subject_id != vehicle.id:
            fail("NOT_FOUND", "Vehicle evidence not found.", status=404)
    value = {
        **payload.model_dump(mode="json"),
        "vehicle_id": vehicle.id,
        "carrier_organisation_id": ctx.org_id,
        "registration_number_snapshot": vehicle.registration_number,
        "vehicle_declarations": vehicle.vehicle_json,
        "prepared_by_user_id": ctx.user.id,
        "prepared_at": instant(db).isoformat(),
    }
    row = Profile(
        vehicle_id=vehicle.id,
        carrier_organisation_id=ctx.org_id,
        revision_number=latest_number(db, Profile, Profile.vehicle_id == vehicle.id),
        profile_json=value,
        content_hash=digest(value),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    vehicle.current_routing_profile_revision_id = row.id
    touch(vehicle)
    record(db, ctx, "ROUTING_PROFILE_REVISED", row)
    return view(row)


def dataset(db, ctx, payload, mode="PRODUCTION"):
    registry_lock(db, exclusive=True)
    require(db, ctx.user, ctx.org_id, "routing.dataset.prepare")
    if mode == "PRODUCTION" and payload.source_kind == "SIMULATION_FIXTURE":
        fail("MODE_MISMATCH", "Simulation datasets are seeded only in the isolated demo.")
    if payload.retention_policy != "PERMITTED_ARCHIVE":
        fail(
            "SOURCE_RETENTION_UNSUPPORTED",
            "Immutable retained graphs require archival rights; "
            "time-limited/non-retainable sources are not ingested.",
        )
    if mode == "PRODUCTION":
        from app.trades.reference import STATES

        if any(n.state_code not in STATES for n in payload.nodes) or any(
            s not in STATES for e in payload.edges for s in (e.ordered_state_sequence or [])
        ):
            fail("ROUTE_SCOPE_UNSUPPORTED", "Production graph uses an unsupported GST state code.")
    data = payload.model_dump(mode="json")
    row = Dataset(
        dataset_code=payload.dataset_code,
        version=payload.version,
        execution_mode=mode,
        dataset_json=data,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        content_hash=digest(data),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    from .persistence import graph_rows

    graph_rows(db, row)
    record(db, ctx, "ROUTING_DATASET_PREPARED", row)
    return view(row)


def dataset_event(db, ctx, ident, payload, action):
    registry_lock(db, exclusive=True)
    row = exists(db, Dataset, ident)
    require(
        db,
        ctx.user,
        ctx.org_id,
        "routing.dataset.review" if action == "REVIEW_APPROVED" else "routing.dataset.publish",
    )
    if payload.content_hash != row.content_hash:
        fail("APPROVAL_HASH_MISMATCH", "Decision must bind the exact dataset hash.")
    if action in {"REVIEW_APPROVED", "PUBLISHED"}:
        independent(ctx, row.created_by_user_id)
    events = list(
        db.scalars(
            select(DatasetEvent)
            .where(DatasetEvent.dataset_revision_id == row.id)
            .order_by(DatasetEvent.created_at, DatasetEvent.id)
        )
    )
    if action == "PUBLISHED" and not any(e.event_type == "REVIEW_APPROVED" for e in events):
        fail("INDEPENDENT_REVIEW_REQUIRED", "Dataset needs independent review before publication.")
    event = DatasetEvent(
        dataset_revision_id=row.id,
        event_type=action,
        dataset_hash=row.content_hash,
        reason=payload.reason,
        actor_user_id=ctx.user.id,
    )
    db.add(event)
    record(db, ctx, "ROUTING_DATASET_" + action, event)
    return {"id": row.id, "status": action, "content_hash": row.content_hash}


def dataset_current(db, row, at, through=None):
    last = db.scalar(
        select(DatasetEvent)
        .where(
            DatasetEvent.dataset_revision_id == row.id,
            DatasetEvent.event_type.in_(["PUBLISHED", "SUSPENDED"]),
        )
        .order_by(DatasetEvent.created_at.desc(), DatasetEvent.id.desc())
    )
    data = row.dataset_json
    return bool(
        last
        and last.event_type == "PUBLISHED"
        and aware(row.valid_from) <= at
        and (row.valid_until is None or (through or at) < aware(row.valid_until))
        and data["retention_policy"] != "NO_CONTENT_STORAGE"
        and (
            data["retention_policy"] != "UNTIL_DATE"
            or data.get("retention_until")
            and (through or at) < aware_from(data["retention_until"])
        )
    )


def aware_from(value):
    from datetime import datetime

    return aware(datetime.fromisoformat(value))


def path_snapshot(data, template, profile, cargo):
    edges = {e["edge_key"]: e for e in data["edges"]}
    nodes, keys = template["ordered_node_keys"], template["ordered_edge_keys"]
    if len(nodes) != len(keys) + 1 or len(set(nodes)) != len(nodes):
        fail("ROUTE_SCOPE_UNSUPPORTED", "Ordered path must be connected and loopless.")
    notices, states, distance, duration = [], [], 0, 0
    known = True
    loaded = (
        None
        if profile["combined_tare_weight_kg"] is None
        else Decimal(profile["combined_tare_weight_kg"]) + Decimal(cargo["gross_weight_kg"])
    )
    measurements = {
        "height": profile["overall_height_mm"],
        "width": profile["overall_width_mm"],
        "length": profile["overall_length_mm"],
        "loaded_weight": loaded,
        "axle_load": profile["maximum_actual_axle_load_kg"],
    }
    for i, key in enumerate(keys):
        edge = edges.get(key)
        if not edge or (edge["from_node_key"], edge["to_node_key"]) != (nodes[i], nodes[i + 1]):
            if (
                not edge
                or edge["directed"]
                or (edge["to_node_key"], edge["from_node_key"]) != (nodes[i], nodes[i + 1])
            ):
                fail("ROUTE_SCOPE_UNSUPPORTED", "Disconnected path or reversed directed edge.")
            sequence = (
                list(reversed(edge["ordered_state_sequence"]))
                if edge["ordered_state_sequence"]
                else None
            )
        else:
            sequence = edge["ordered_state_sequence"]
        if sequence is None:
            known = False
        else:
            for state in sequence:
                if not states or states[-1] != state:
                    states.append(state)
        distance += edge["distance_meters"]
        speed = profile.get("speed_cap_kph")
        seconds = (
            max(
                edge["estimated_driving_seconds"],
                (edge["distance_meters"] * 18 + speed * 5 - 1) // (speed * 5),
            )
            if speed
            else edge["estimated_driving_seconds"]
        )
        duration += seconds
        if not set(profile["supported_cargo_profile_codes"]) & set(
            edge["allowed_vehicle_profile_codes"]
        ):
            notices.append(
                {"code": "VEHICLE_PROFILE_UNSUPPORTED", "outcome": "FAIL", "edge_key": key}
            )
        for kind, measured in measurements.items():
            attr = "maximum_" + kind + ("_mm" if kind in {"height", "width", "length"} else "_kg")
            limit = edge.get(attr)
            coverage = edge["assessment_coverage"].get(kind, "UNKNOWN")
            outcome = (
                "UNKNOWN"
                if coverage == "UNKNOWN"
                or measured is None
                or (coverage == "ASSESSED_LIMIT" and limit is None)
                else "FAIL"
                if limit is not None and Decimal(str(measured)) > Decimal(str(limit))
                else "PASS"
            )
            notices.append(
                {
                    "code": "ROUTE_" + kind.upper(),
                    "edge_key": key,
                    "outcome": outcome,
                    "observed": str(measured) if measured is not None else None,
                    "expected_maximum": str(limit) if limit is not None else None,
                    "source_refs": edge["restriction_refs"],
                }
            )
    return {
        "dataset_revision_id": template.get("dataset_revision_id"),
        "ordered_node_keys": nodes,
        "ordered_edge_keys": keys,
        "distance_meters": distance,
        "estimated_driving_seconds": duration,
        "state_sequence": states if known else None,
        "estimated_loaded_vehicle_weight_kg": str(loaded) if loaded is not None else None,
        "restriction_assessment": "FAIL"
        if any(n["outcome"] == "FAIL" for n in notices)
        else "UNKNOWN"
        if any(n["outcome"] == "UNKNOWN" for n in notices)
        else "PASS",
        "restriction_notices": notices,
        "data_provenance": {
            "source_reference": data["source_reference"],
            "version": data["version"],
            "attribution_text": data["attribution_text"],
            "retention_policy": data["retention_policy"],
            "export_allowed": data["export_allowed"],
        },
        "source_valid_until": data["valid_until"],
        "limitations": data["limitations"],
    }


def materialize(db, ctx, ident, payload):
    trade, cn = planning(db, ctx, ident, "tradetwin.plan.prepare", True)
    before_pickup(cn)
    base = base_context(db, trade, cn)
    if [str(payload.pickup_location_revision_id), str(payload.drop_location_revision_id)] != [
        base["pickup_location_revision_id"],
        base["drop_location_revision_id"],
    ]:
        fail("ROUTING_INPUT_MISSING", "Confirm current pickup and drop pins first.")
    data = db.get(Dataset, str(payload.dataset_revision_id_or_provider_connection_id))
    if data is None:
        from .models import Provider

        connection = db.get(Provider, str(payload.dataset_revision_id_or_provider_connection_id))
        if connection:
            from .providers import capability

            capability(connection, trade.execution_mode, payload.departure_at)
            fail(
                "CORRIDOR_COVERAGE_UNKNOWN",
                "Provider connection needs a reviewed, retainable corridor record "
                "before executable template generation.",
            )
        fail(
            "PROVIDER_NOT_CONFIGURED",
            "Select a published retained dataset; no approved routing provider is configured.",
        )
    if data.execution_mode != trade.execution_mode:
        fail("MODE_MISMATCH", "Dataset and trade environments must match.")
    if not dataset_current(db, data, instant(db)):
        fail("SOURCE_RETENTION_UNSUPPORTED", "Dataset must be published, current and retainable.")
    profile_row = exists(db, Profile, payload.vehicle_profile_revision_id)
    profile = profile_row.profile_json
    start, end = [
        exists(db, Location, i)
        for i in (base["pickup_location_revision_id"], base["drop_location_revision_id"])
    ]
    # Only exact retained access nodes are snapped; no centroid or straight-line fallback.
    graph = nx.DiGraph()
    for node in sorted(data.dataset_json["nodes"], key=lambda n: n["node_key"]):
        graph.add_node(node["node_key"])
    key = "distance_meters" if payload.objective == "DISTANCE" else "estimated_driving_seconds"
    for edge in sorted(data.dataset_json["edges"], key=lambda e: e["edge_key"]):
        if not set(profile["supported_cargo_profile_codes"]) & set(
            edge["allowed_vehicle_profile_codes"]
        ):
            continue
        # Edge-node expansion also supports parallel routes without MultiDiGraph.
        edge_node = "edge:" + edge["edge_key"]
        graph.add_edge(edge["from_node_key"], edge_node, weight=edge[key])
        graph.add_edge(edge_node, edge["to_node_key"], weight=0)
        if not edge["directed"]:
            reverse = "reverse:" + edge["edge_key"]
            graph.add_edge(edge["to_node_key"], reverse, weight=edge[key])
            graph.add_edge(reverse, edge["from_node_key"], weight=0)

    def access_node(location, kind):
        values = [
            n["node_key"]
            for n in data.dataset_json["nodes"]
            if n["node_kind"] == kind
            and Decimal(n["latitude"]) == location.latitude
            and Decimal(n["longitude"]) == location.longitude
            and n["state_code"] == location.state_code
        ]
        if len(values) != 1:
            fail(
                "ROUTING_INPUT_MISSING",
                "Dataset does not contain the confirmed gate; no off-road fallback is allowed.",
            )
        return values[0]

    origin, destination = access_node(start, "PICKUP_ACCESS"), access_node(end, "DROP_ACCESS")
    results = []
    try:
        for path in islice(
            nx.shortest_simple_paths(graph, origin, destination, weight="weight"), 20
        ):
            node_keys = [n for n in path if not n.startswith(("edge:", "reverse:"))]
            edge_keys = [n.split(":", 1)[1] for n in path if n.startswith(("edge:", "reverse:"))]
            value = {
                "ordered_node_keys": node_keys,
                "ordered_edge_keys": edge_keys,
                "origin_location_revision_id": start.id,
                "drop_location_revision_id": end.id,
                "dataset_revision_id": data.id,
                "state_sequence_basis": "SIMULATION"
                if trade.execution_mode == "SIMULATION"
                else "GRAPH_TOPOLOGY",
                "generation_objective": payload.objective,
            }
            snapshot = path_snapshot(data.dataset_json, value, profile, base["cargo_snapshot"])
            if snapshot["restriction_assessment"] == "FAIL":
                continue
            value["state_sequence"] = snapshot["state_sequence"]
            code = cn.id + ":" + digest(value)[:20]
            row = db.scalar(select(Template).where(Template.template_code == code))
            if not row:
                row = Template(
                    consignment_id=cn.id,
                    template_code=code,
                    revision_number=1,
                    dataset_revision_id=data.id,
                    template_json=value,
                    content_hash=digest(value),
                    created_by_user_id=ctx.user.id,
                )
                db.add(row)
                db.flush()
            results.append(view(row))
            if len(results) == payload.maximum_alternatives:
                break
    except nx.NetworkXNoPath:
        pass
    return {
        "job_state": "COMPLETED",
        "templates": results,
        "execution_mode": trade.execution_mode,
        "limitations": [
            "Bounded loopless retained graph paths; not global freight-price optimisation."
        ],
    }


def generate(db, ctx, ident, payload):
    from app.document_desk.models import Job, Outbox

    from .models import Generation

    trade, cn = planning(db, ctx, ident, "tradetwin.plan.prepare", True)
    before_pickup(cn)
    inputs = {
        "request": payload.model_dump(mode="json"),
        "context_hash": base_context(db, trade, cn)["planning_context_hash"],
    }
    row = Generation(
        trade_id=trade.id,
        consignment_id=cn.id,
        input_json=inputs,
        content_hash=digest(inputs),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    job = Job(
        trade_id=trade.id,
        stage="ROUTE_GENERATION",
        input_fingerprint=digest({"generation_id": row.id, "input_hash": row.content_hash}),
        pipeline_version="RETAINED_ROAD_1",
        schema_version="ROUTE_GENERATION_V1",
        configuration_hash=digest(
            {"algorithm": "NETWORKX_YEN_3.5", "maximum_alternatives": payload.maximum_alternatives}
        ),
        requested_by_user_id=ctx.user.id,
        requested_by_organization_id=ctx.org_id,
        request_json={"generation_id": row.id, "consignment_id": cn.id},
        created_by=ctx.user.id,
    )
    db.add(job)
    db.flush()
    row.job_id = job.id
    db.add(Outbox(job_id=job.id))
    record(db, ctx, "ROUTE_GENERATION_QUEUED", row, trade, cn)
    return {"job_id": row.id, "job_state": row.job_state}


def complete_generation(db, ctx, ident):
    from .models import Generation
    from .schemas import GenerateInput

    row = exists(db, Generation, ident)
    trade, cn = planning(db, ctx, row.consignment_id, "tradetwin.plan.prepare", True)
    if row.job_state != "QUEUED":
        return
    if base_context(db, trade, cn)["planning_context_hash"] != row.input_json["context_hash"]:
        row.job_state, row.result_json = "FAILED", {"error_code": "RFQ_CONTEXT_STALE"}
        return
    row.result_json = materialize(
        db, ctx, cn.id, GenerateInput.model_validate(row.input_json["request"])
    )
    row.job_state = "COMPLETED"
    record(db, ctx, "ROUTE_GENERATION_COMPLETED", row, trade, cn)
