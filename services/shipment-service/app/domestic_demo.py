from datetime import UTC, datetime, timedelta

from app.models import Shipment
from app.schemas import ShipmentCreate, ShipmentEventCreate
from app.service import add_event, create_shipment, get_shipment, sync_graph


def seed_domestic_demo(db, graph):
    reference = "TT-DEMO-TN-KA-MH"
    existing = db.query(Shipment).filter(Shipment.shipment_reference == reference).first()
    if existing:
        sync_graph(db, graph, existing.id)
        return get_shipment(db, existing.id)
    now = datetime.now(UTC).replace(microsecond=0)
    chennai = dict(state="Tamil Nadu", city="Chennai", pincode="600001")
    bengaluru = dict(state="Karnataka", city="Bengaluru", pincode="560001")
    pune = dict(state="Maharashtra", city="Pune", pincode="411001")
    payload = ShipmentCreate.model_validate(
        dict(
            shipment_reference=reference,
            exporter_country="India",
            importer_country="India",
            transport_mode="ROAD",
            planned_departure_at=now - timedelta(days=1),
            planned_arrival_at=now + timedelta(days=2),
            domestic=dict(
                origin=chennai,
                destination=pune,
                consignor_name="Chennai Distribution",
                consignee_name="Pune Retail",
                registered_consignor=True,
                ordinary_goods=True,
            ),
            consignments=[
                dict(
                    product_name=name,
                    product_description=description,
                    quantity=quantity,
                    declared_value=value,
                    currency="INR",
                    country_of_origin="India",
                    destination_country="India",
                    proposed_hs_code=code,
                    domestic=dict(destination=destination, consignment_value=value),
                )
                for name, description, quantity, value, code, destination in [
                    ("Cotton shirts", "Packed cotton shirts", 100, 75000, "620520", pune),
                    (
                        "Stationery",
                        "Packed notebooks and paper supplies",
                        40,
                        20000,
                        "482010",
                        bengaluru,
                    ),
                ]
            ],
            route_legs=[
                dict(
                    sequence_number=i,
                    origin_country="India",
                    destination_country="India",
                    transport_mode="ROAD",
                    carrier_name="TradeTwin Demo Transport",
                    domestic=dict(origin=origin, destination=destination, distance_km=distance),
                )
                for i, origin, destination, distance in [
                    (1, chennai, bengaluru, 350),
                    (2, bengaluru, pune, 840),
                ]
            ],
        )
    )
    shipment = create_shipment(db, payload, graph)
    books = next(item for item in shipment.consignments if item.product_name == "Stationery")
    for i, (event_type, location, consignment_id) in enumerate(
        [
            ("CREATED", chennai, None),
            ("LOADED", chennai, None),
            ("ARRIVED_AT_HUB", bengaluru, None),
            ("DELIVERED", bengaluru, books.id),
        ]
    ):
        add_event(
            db,
            shipment.id,
            ShipmentEventCreate(
                event_type=event_type,
                location_country="India",
                consignment_id=consignment_id,
                occurred_at=now - timedelta(hours=20 - i),
                metadata={"location": location, "source": "domestic-demo"},
            ),
            graph,
        )
    return get_shipment(db, shipment.id)
