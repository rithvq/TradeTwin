from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from tradetwin_security import ProfileMiddleware, migrate_ownership

from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.domestic import STATES, migrate_domestic, validate_domestic
from app.domestic_demo import seed_domestic_demo as seed_demo
from app.graph import ShipmentGraph, build_graph_response, load_graph_shipment
from app.schemas import (
    ConsignmentCreate,
    ConsignmentRead,
    ShipmentCreate,
    ShipmentEventCreate,
    ShipmentEventRead,
    ShipmentGraphRead,
    ShipmentLegCreate,
    ShipmentLegRead,
    ShipmentRead,
    TimelineRead,
)
from app.service import (
    add_consignment,
    add_event,
    add_route_leg,
    create_shipment,
    delete_shipment,
    get_shipment,
    get_timeline,
    list_shipments,
    retry_pending_graph_sync,
    sync_graph,
)

SERVICE_NAME = "shipment-service"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    migrate_ownership(engine, Base.metadata)
    migrate_domestic(engine)
    Base.metadata.create_all(bind=engine)
    graph = ShipmentGraph()
    app.state.graph = graph
    if settings.seed_demo_data:
        with SessionLocal() as db:
            seed_demo(db, graph)
    try:
        yield
    finally:
        graph.close()


app = FastAPI(title="TradeTwin Shipment Service", version="0.1.0", lifespan=lifespan)


@app.get("/locations/states")
def indian_states():
    return list(STATES)


app.add_middleware(ProfileMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        graph = app.state.graph
        if graph._driver is not None:
            graph._driver.verify_connectivity()
        with SessionLocal() as db:
            if not retry_pending_graph_sync(db, graph):
                raise RuntimeError("Graph projection is awaiting synchronization")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Shipment dependencies unavailable") from exc
    return {"status": "ok", "service": SERVICE_NAME}


def get_graph() -> ShipmentGraph:
    return app.state.graph


@app.post("/demo/seed", response_model=ShipmentRead, tags=["demo"])
def load_demo_endpoint(
    db: Session = Depends(get_db),
    graph: ShipmentGraph = Depends(get_graph),
):
    return seed_demo(db, graph)


@app.post("/shipments", response_model=ShipmentRead, status_code=201)
def create_shipment_endpoint(
    payload: ShipmentCreate,
    db: Session = Depends(get_db),
    graph: ShipmentGraph = Depends(get_graph),
):
    try:
        validate_domestic(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return create_shipment(db, payload, graph)


@app.get("/shipments", response_model=list[ShipmentRead])
def list_shipments_endpoint(db: Session = Depends(get_db)):
    return list_shipments(db)


@app.get("/shipments/{shipment_id}", response_model=ShipmentRead)
def get_shipment_endpoint(shipment_id: str, db: Session = Depends(get_db)):
    return get_shipment(db, shipment_id)


@app.delete("/shipments/{shipment_id}", status_code=204)
def delete_shipment_endpoint(
    shipment_id: str,
    db: Session = Depends(get_db),
    graph: ShipmentGraph = Depends(get_graph),
):
    delete_shipment(db, shipment_id, graph)


@app.post("/shipments/{shipment_id}/consignments", response_model=ConsignmentRead, status_code=201)
def add_consignment_endpoint(
    shipment_id: str,
    payload: ConsignmentCreate,
    db: Session = Depends(get_db),
    graph: ShipmentGraph = Depends(get_graph),
):
    return add_consignment(db, shipment_id, payload, graph)


@app.post("/shipments/{shipment_id}/route-legs", response_model=ShipmentLegRead, status_code=201)
def add_route_leg_endpoint(
    shipment_id: str,
    payload: ShipmentLegCreate,
    db: Session = Depends(get_db),
    graph: ShipmentGraph = Depends(get_graph),
):
    return add_route_leg(db, shipment_id, payload, graph)


@app.post("/shipments/{shipment_id}/events", response_model=ShipmentEventRead, status_code=201)
def add_event_endpoint(
    shipment_id: str,
    payload: ShipmentEventCreate,
    db: Session = Depends(get_db),
    graph: ShipmentGraph = Depends(get_graph),
):
    return add_event(db, shipment_id, payload, graph)


@app.get("/shipments/{shipment_id}/timeline", response_model=TimelineRead)
def get_timeline_endpoint(shipment_id: str, db: Session = Depends(get_db)):
    return TimelineRead(shipment_id=shipment_id, events=get_timeline(db, shipment_id))


@app.get("/shipments/{shipment_id}/graph", response_model=ShipmentGraphRead)
def get_graph_endpoint(
    shipment_id: str,
    db: Session = Depends(get_db),
    graph: ShipmentGraph = Depends(get_graph),
):
    shipment = load_graph_shipment(db, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
    sync_graph(db, graph, shipment_id)
    return build_graph_response(shipment)
