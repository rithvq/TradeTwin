from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.graph import ShipmentGraph, load_graph_shipment
from app.models import (
    Consignment,
    CustomsStatus,
    Shipment,
    ShipmentEvent,
    ShipmentEventType,
    ShipmentLeg,
    ShipmentStatus,
)
from app.schemas import ConsignmentCreate, ShipmentCreate, ShipmentEventCreate, ShipmentLegCreate


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
    db.delete(shipment)
    db.commit()
    graph.delete_shipment(shipment_id)


def create_shipment(db: Session, payload: ShipmentCreate, graph: ShipmentGraph) -> Shipment:
    shipment = Shipment(
        shipment_reference=payload.shipment_reference,
        exporter_country=payload.exporter_country,
        importer_country=payload.importer_country,
        transport_mode=payload.transport_mode,
        planned_departure_at=payload.planned_departure_at,
        planned_arrival_at=payload.planned_arrival_at,
    )
    shipment.consignments = [
        Consignment(**consignment.model_dump()) for consignment in payload.consignments
    ]
    shipment.route_legs = [ShipmentLeg(**leg.model_dump()) for leg in payload.route_legs]
    db.add(shipment)
    commit_or_409(db, "Shipment reference already exists")
    db.refresh(shipment)
    sync_graph(db, graph, shipment.id)
    return get_shipment(db, shipment.id)


def add_consignment(
    db: Session, shipment_id: str, payload: ConsignmentCreate, graph: ShipmentGraph
) -> Consignment:
    get_shipment(db, shipment_id)
    consignment = Consignment(shipment_id=shipment_id, **payload.model_dump())
    db.add(consignment)
    db.commit()
    db.refresh(consignment)
    sync_graph(db, graph, shipment_id)
    return consignment


def add_route_leg(
    db: Session, shipment_id: str, payload: ShipmentLegCreate, graph: ShipmentGraph
) -> ShipmentLeg:
    get_shipment(db, shipment_id)
    leg = ShipmentLeg(shipment_id=shipment_id, **payload.model_dump())
    db.add(leg)
    db.commit()
    db.refresh(leg)
    sync_graph(db, graph, shipment_id)
    return leg


def add_event(
    db: Session, shipment_id: str, payload: ShipmentEventCreate, graph: ShipmentGraph
) -> ShipmentEvent:
    shipment = get_shipment(db, shipment_id)
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
    apply_event_state(shipment, event)
    db.commit()
    db.refresh(event)
    sync_graph(db, graph, shipment_id)
    return event


def apply_event_state(shipment: Shipment, event: ShipmentEvent) -> None:
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
        for consignment in shipment.consignments:
            if consignment.destination_country != location:
                consignment.customs_status = transit_status(location)
        return

    if event_type == ShipmentEventType.UNLOADED:
        shipment.status = ShipmentStatus.PARTIALLY_UNLOADED
        for consignment in target_consignments(shipment, event):
            if consignment.destination_country == location:
                consignment.customs_status = import_status(location)
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


def transit_status(country: str) -> str:
    return f"{country.upper().replace(' ', '_')}_TRANSIT"


def import_status(country: str) -> str:
    return f"{country.upper().replace(' ', '_')}_IMPORT"


def get_timeline(db: Session, shipment_id: str) -> list[ShipmentEvent]:
    get_shipment(db, shipment_id)
    return (
        db.query(ShipmentEvent)
        .filter(ShipmentEvent.shipment_id == shipment_id)
        .order_by(ShipmentEvent.occurred_at.asc())
        .all()
    )


def sync_graph(db: Session, graph: ShipmentGraph, shipment_id: str) -> None:
    shipment = load_graph_shipment(db, shipment_id)
    if shipment is not None:
        graph.sync_shipment(shipment)


def seed_demo(db: Session, graph: ShipmentGraph) -> None:
    if db.query(Shipment).first() is not None:
        return

    now = datetime.now(UTC).replace(microsecond=0)
    payload = ShipmentCreate(
        shipment_reference="TT-DEMO-IND-UAE-DEU",
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


def commit_or_409(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from exc
