from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.domestic import Location, same_place
from app.graph import ShipmentGraph, load_graph_shipment
from app.models import (
    Consignment,
    CustomsStatus,
    GraphSyncTask,
    Shipment,
    ShipmentEvent,
    ShipmentEventType,
    ShipmentLeg,
    ShipmentStatus,
    new_id,
)
from app.schemas import ConsignmentCreate, ShipmentCreate, ShipmentEventCreate, ShipmentLegCreate

DEMO_SHIPMENT_REFERENCE = "TT-DEMO-IND-UAE-DEU"


def list_shipments(db: Session) -> list[Shipment]:
    return (
        db.query(Shipment)
        .options(selectinload(Shipment.consignments), selectinload(Shipment.route_legs))
        .order_by(Shipment.created_at.desc())
        .all()
    )


def get_shipment(db: Session, shipment_id: str) -> Shipment:
    shipment = (
        db.query(Shipment)
        .options(selectinload(Shipment.consignments), selectinload(Shipment.route_legs))
        .filter(Shipment.id == shipment_id)
        .first()
    )
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    return shipment


def delete_shipment(db: Session, shipment_id: str, graph: ShipmentGraph) -> None:
    shipment = get_shipment(db, shipment_id)
    queue_graph_sync(db, shipment_id)
    db.delete(shipment)
    db.commit()
    retry_graph_sync(db, graph, shipment_id)


def create_shipment(db: Session, payload: ShipmentCreate, graph: ShipmentGraph) -> Shipment:
    shipment = Shipment(
        id=new_id(),
        shipment_reference=payload.shipment_reference,
        exporter_country=payload.exporter_country,
        importer_country=payload.importer_country,
        transport_mode=payload.transport_mode,
        planned_departure_at=payload.planned_departure_at,
        planned_arrival_at=payload.planned_arrival_at,
        domestic=payload.domestic.model_dump() if payload.domestic else None,
    )
    shipment.consignments = [
        Consignment(**consignment.model_dump()) for consignment in payload.consignments
    ]
    shipment.route_legs = [ShipmentLeg(**leg.model_dump()) for leg in payload.route_legs]
    db.add(shipment)
    queue_graph_sync(db, shipment.id)
    commit_or_409(db, "Shipment reference already exists")
    db.refresh(shipment)
    sync_graph(db, graph, shipment.id)
    return get_shipment(db, shipment.id)


def add_consignment(
    db: Session, shipment_id: str, payload: ConsignmentCreate, graph: ShipmentGraph
) -> Consignment:
    shipment = get_shipment(db, shipment_id)
    if shipment.domestic:
        if (
            not payload.domestic
            or payload.currency != "INR"
            or payload.destination_country != "India"
        ):
            raise HTTPException(422, "Provide an Indian delivery location and INR value")
        if not any(
            leg.domestic
            and same_place(payload.domestic.destination.model_dump(), leg.domestic["destination"])
            for leg in shipment.route_legs
        ):
            raise HTTPException(422, "Consignment destination must be on the route")
    consignment = Consignment(shipment_id=shipment_id, **payload.model_dump())
    db.add(consignment)
    queue_graph_sync(db, shipment_id)
    db.commit()
    db.refresh(consignment)
    sync_graph(db, graph, shipment_id)
    return consignment


def add_route_leg(
    db: Session, shipment_id: str, payload: ShipmentLegCreate, graph: ShipmentGraph
) -> ShipmentLeg:
    shipment = get_shipment(db, shipment_id)
    if any(leg.sequence_number == payload.sequence_number for leg in shipment.route_legs):
        raise HTTPException(status_code=409, detail="Route leg sequence number already exists")
    if shipment.domestic:
        raise HTTPException(
            409,
            "Create a shipment with its complete domestic route; "
            "route amendments require a new plan",
        )
    leg = ShipmentLeg(shipment_id=shipment_id, **payload.model_dump())
    db.add(leg)
    queue_graph_sync(db, shipment_id)
    db.commit()
    db.refresh(leg)
    sync_graph(db, graph, shipment_id)
    return leg


def add_event(
    db: Session, shipment_id: str, payload: ShipmentEventCreate, graph: ShipmentGraph
) -> ShipmentEvent:
    shipment = get_shipment(db, shipment_id)
    if shipment.domestic:
        try:
            location = Location.model_validate(payload.metadata.get("location"))
        except ValueError as exc:
            raise HTTPException(422, "Select the event state, city and PIN code") from exc
        stops = [shipment.domestic["origin"]] + [
            leg.domestic["destination"] for leg in shipment.route_legs if leg.domestic
        ]
        if payload.location_country != "India" or not any(
            same_place(location.model_dump(), stop) for stop in stops
        ):
            raise HTTPException(422, "Event location must be an Indian stop on the shipment route")
        if payload.event_type == ShipmentEventType.ROUTE_CHANGED:
            raise HTTPException(
                422, "A route change requires a revised plan; this event is unavailable"
            )
        if payload.event_type == ShipmentEventType.DELIVERED:
            targets = [
                item
                for item in shipment.consignments
                if not payload.consignment_id or item.id == payload.consignment_id
            ]
            if any(
                not same_place(item.domestic["destination"], location.model_dump())
                for item in targets
            ):
                raise HTTPException(
                    422, "Delivery must occur at each targeted consignment's destination"
                )
    if payload.consignment_id and not any(
        consignment.id == payload.consignment_id for consignment in shipment.consignments
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consignment does not belong to shipment",
        )

    event = ShipmentEvent(
        shipment_id=shipment_id,
        consignment_id=payload.consignment_id,
        event_type=payload.event_type.value,
        location_country=payload.location_country,
        occurred_at=payload.occurred_at,
        event_metadata=payload.metadata,
    )
    db.add(event)
    db.flush()
    # Rebuild from event time so a late-entered historical event cannot rewind the twin.
    shipment.status = ShipmentStatus.CREATED
    for consignment in shipment.consignments:
        consignment.customs_status = CustomsStatus.PENDING
    timeline = (
        db.query(ShipmentEvent)
        .filter(ShipmentEvent.shipment_id == shipment_id)
        .order_by(ShipmentEvent.occurred_at.asc(), ShipmentEvent.id.asc())
        .all()
    )
    for recorded_event in timeline:
        apply_event_state(shipment, recorded_event)
    queue_graph_sync(db, shipment_id)
    db.commit()
    db.refresh(event)
    sync_graph(db, graph, shipment_id)
    return event


def apply_event_state(shipment: Shipment, event: ShipmentEvent) -> None:
    if shipment.domestic:
        apply_domestic_state(shipment, event)
        return
    event_type = ShipmentEventType(event.event_type)
    location = event.location_country

    if event_type == ShipmentEventType.CREATED:
        shipment.status = ShipmentStatus.CREATED
        return

    if event_type == ShipmentEventType.LOADED:
        shipment.status = ShipmentStatus.IN_TRANSIT
        for consignment in target_consignments(shipment, event):
            consignment.customs_status = CustomsStatus.LOADED
        return

    if event_type == ShipmentEventType.ARRIVED_AT_TRANSIT_PORT:
        shipment.status = ShipmentStatus.AT_TRANSIT_PORT
        for consignment in target_consignments(shipment, event):
            if (
                not consignment.customs_status.endswith("_IMPORT")
                and consignment.destination_country != location
            ):
                consignment.customs_status = transit_status(location)
        return

    if event_type == ShipmentEventType.UNLOADED:
        shipment.status = ShipmentStatus.PARTIALLY_UNLOADED
        for consignment in target_consignments(shipment, event):
            if consignment.destination_country == location:
                consignment.customs_status = import_status(location)
            else:
                consignment.customs_status = transit_status(location)
        if shipment.consignments and all(
            item.customs_status.endswith("_IMPORT") for item in shipment.consignments
        ):
            shipment.status = "DELIVERED"
        return

    if event_type in {
        ShipmentEventType.TRANSSHIPMENT,
        ShipmentEventType.ROUTE_CHANGED,
        ShipmentEventType.TEMPORARY_STORAGE,
        ShipmentEventType.CONTAINER_OPENED,
        ShipmentEventType.CONTAINER_RESEALED,
    }:
        shipment.status = ShipmentStatus.IN_TRANSIT


def target_consignments(shipment: Shipment, event: ShipmentEvent) -> list[Consignment]:
    if event.consignment_id is None:
        return list(shipment.consignments)
    return [
        consignment
        for consignment in shipment.consignments
        if consignment.id == event.consignment_id
    ]


def apply_domestic_state(shipment, event):
    location = event.event_metadata.get("location", {})
    for item in target_consignments(shipment, event):
        if item.customs_status == "DELIVERED":
            continue
        if event.event_type in {"UNLOADED", "DELIVERED"}:
            item.customs_status = (
                "DELIVERED" if same_place(item.domestic["destination"], location) else "AT_HUB"
            )
        elif event.event_type in {"ARRIVED_AT_HUB", "ARRIVED_AT_TRANSIT_PORT", "TEMPORARY_STORAGE"}:
            item.customs_status = "AT_HUB"
        elif event.event_type in {"LOADED", "TRANSSHIPMENT", "CONTAINER_RESEALED"}:
            item.customs_status = "IN_TRANSIT"
    statuses = [item.customs_status for item in shipment.consignments]
    if statuses and all(value == "DELIVERED" for value in statuses):
        shipment.status = "DELIVERED"
    elif "DELIVERED" in statuses:
        shipment.status = "PARTIALLY_DELIVERED"
    elif "AT_HUB" in statuses:
        shipment.status = "AT_HUB"
    elif "IN_TRANSIT" in statuses:
        shipment.status = "IN_TRANSIT"


def transit_status(country: str) -> str:
    return f"{country.upper().replace(' ', '_')}_TRANSIT"


def import_status(country: str) -> str:
    return f"{country.upper().replace(' ', '_')}_IMPORT"


def get_timeline(db: Session, shipment_id: str) -> list[ShipmentEvent]:
    get_shipment(db, shipment_id)
    return (
        db.query(ShipmentEvent)
        .filter(ShipmentEvent.shipment_id == shipment_id)
        .order_by(ShipmentEvent.occurred_at.asc(), ShipmentEvent.id.asc())
        .all()
    )


def sync_graph(db: Session, graph: ShipmentGraph, shipment_id: str) -> None:
    queue_graph_sync(db, shipment_id)
    db.commit()
    retry_graph_sync(db, graph, shipment_id)


def queue_graph_sync(db: Session, shipment_id: str) -> None:
    if db.get(GraphSyncTask, shipment_id) is None:
        db.add(GraphSyncTask(shipment_id=shipment_id))


def retry_graph_sync(db: Session, graph: ShipmentGraph, shipment_id: str) -> bool:
    shipment = load_graph_shipment(db, shipment_id)
    synced = graph.sync_shipment(shipment) if shipment else graph.delete_shipment(shipment_id)
    if synced:
        task = db.get(GraphSyncTask, shipment_id)
        if task:
            db.delete(task)
            db.commit()
    return synced


def retry_pending_graph_sync(db: Session, graph: ShipmentGraph) -> bool:
    from sqlalchemy import select
    from tradetwin_security import identity

    # Readiness repairs queued projections for every owner, without exposing their records.
    table = GraphSyncTask.__table__
    tasks = db.connection().execute(select(table.c.shipment_id, table.c.owner_id)).all()
    results = []
    for shipment_id, owner in tasks:
        context_token = identity.set({"id": owner})
        try:
            results.append(retry_graph_sync(db, graph, shipment_id))
        finally:
            identity.reset(context_token)
    return all(results)


def seed_demo(db: Session, graph: ShipmentGraph) -> Shipment:
    existing = (
        db.query(Shipment).filter(Shipment.shipment_reference == DEMO_SHIPMENT_REFERENCE).first()
    )
    if existing is not None:
        sync_graph(db, graph, existing.id)
        return get_shipment(db, existing.id)

    now = datetime.now(UTC).replace(microsecond=0)
    payload = ShipmentCreate(
        shipment_reference=DEMO_SHIPMENT_REFERENCE,
        exporter_country="India",
        importer_country="Germany",
        transport_mode="SEA",
        planned_departure_at=now,
        planned_arrival_at=now + timedelta(days=21),
        consignments=[
            ConsignmentCreate(
                product_name="Lithium batteries",
                product_description="Rechargeable lithium battery packs for industrial equipment.",
                quantity=120,
                declared_value="18000.00",
                currency="USD",
                country_of_origin="India",
                destination_country="Germany",
            ),
            ConsignmentCreate(
                product_name="Consumer electronics",
                product_description="Packaged consumer electronic devices for retail distribution.",
                quantity=240,
                declared_value="32000.00",
                currency="USD",
                country_of_origin="India",
                destination_country="UAE",
            ),
        ],
        route_legs=[
            ShipmentLegCreate(
                sequence_number=1,
                origin_country="India",
                destination_country="UAE",
                transport_mode="SEA",
                carrier_name="TradeTwin Demo Line",
            ),
            ShipmentLegCreate(
                sequence_number=2,
                origin_country="UAE",
                destination_country="Germany",
                transport_mode="SEA",
                carrier_name="TradeTwin Demo Line",
            ),
        ],
    )
    shipment = create_shipment(db, payload, graph)
    lithium = next(
        item for item in shipment.consignments if item.product_name == "Lithium batteries"
    )
    electronics = next(
        item for item in shipment.consignments if item.product_name == "Consumer electronics"
    )

    demo_events = [
        ShipmentEventCreate(
            event_type=ShipmentEventType.CREATED,
            location_country="India",
            occurred_at=now,
            metadata={"source": "demo-seed"},
        ),
        ShipmentEventCreate(
            consignment_id=lithium.id,
            event_type=ShipmentEventType.LOADED,
            location_country="India",
            occurred_at=now + timedelta(hours=2),
            metadata={"source": "demo-seed"},
        ),
        ShipmentEventCreate(
            consignment_id=electronics.id,
            event_type=ShipmentEventType.LOADED,
            location_country="India",
            occurred_at=now + timedelta(hours=2, minutes=5),
            metadata={"source": "demo-seed"},
        ),
        ShipmentEventCreate(
            event_type=ShipmentEventType.ARRIVED_AT_TRANSIT_PORT,
            location_country="UAE",
            occurred_at=now + timedelta(days=7),
            metadata={"source": "demo-seed"},
        ),
        ShipmentEventCreate(
            consignment_id=electronics.id,
            event_type=ShipmentEventType.UNLOADED,
            location_country="UAE",
            occurred_at=now + timedelta(days=7, hours=3),
            metadata={"source": "demo-seed"},
        ),
    ]
    for event in demo_events:
        add_event(db, shipment.id, event, graph)

    return get_shipment(db, shipment.id)


def commit_or_409(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc
