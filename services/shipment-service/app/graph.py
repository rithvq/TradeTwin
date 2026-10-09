import logging
from collections.abc import Sequence

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import Shipment
from app.schemas import GraphEdge, GraphNode, ShipmentGraphRead

logger = logging.getLogger(__name__)


class ShipmentGraph:
    def __init__(self) -> None:
        self._driver = None
        if settings.neo4j_enabled:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()

    def sync_shipment(self, shipment: Shipment) -> bool:
        if self._driver is None:
            return True
        try:
            with self._driver.session() as session:
                session.execute_write(self._write_shipment, shipment)
            return True
        except (Neo4jError, ServiceUnavailable):
            logger.exception("Shipment graph synchronization failed for %s", shipment.id)
            return False

    def delete_shipment(self, shipment_id: str) -> bool:
        if self._driver is None:
            return True
        try:
            with self._driver.session() as session:
                session.execute_write(self._delete_shipment, shipment_id)
            return True
        except (Neo4jError, ServiceUnavailable):
            logger.exception("Shipment graph deletion failed for %s", shipment_id)
            return False

    @staticmethod
    def _write_shipment(tx, shipment: Shipment) -> None:
        if shipment.domestic:
            ShipmentGraph._write_domestic(tx, shipment)
            return
        tx.run(
            """
            MERGE (s:Shipment {id: $id})
            SET s.reference = $reference,
                s.status = $status,
                s.exporterCountry = $exporter_country,
                s.importerCountry = $importer_country,
                s.transportMode = $transport_mode
            """,
            id=shipment.id,
            reference=shipment.shipment_reference,
            status=shipment.status,
            exporter_country=shipment.exporter_country,
            importer_country=shipment.importer_country,
            transport_mode=shipment.transport_mode,
        )

        for consignment in shipment.consignments:
            tx.run(
                """
                MATCH (s:Shipment {id: $shipment_id})
                MERGE (c:Consignment {id: $id})
                SET c.productName = $product_name,
                    c.customsStatus = $customs_status,
                    c.destinationCountry = $destination_country
                MERGE (origin:Country {name: $origin_country})
                MERGE (destination:Country {name: $destination_country})
                MERGE (s)-[:CONTAINS]->(c)
                MERGE (c)-[:ORIGINATES_IN]->(origin)
                MERGE (c)-[:DESTINED_FOR]->(destination)
                """,
                shipment_id=shipment.id,
                id=consignment.id,
                product_name=consignment.product_name,
                customs_status=consignment.customs_status,
                origin_country=consignment.country_of_origin,
                destination_country=consignment.destination_country,
            )

        for leg in shipment.route_legs:
            tx.run(
                """
                MATCH (s:Shipment {id: $shipment_id})
                MERGE (leg:RouteLeg {id: $id})
                SET leg.sequenceNumber = $sequence_number,
                    leg.originCountry = $origin_country,
                    leg.destinationCountry = $destination_country,
                    leg.transportMode = $transport_mode,
                    leg.carrierName = $carrier_name
                MERGE (origin:Country {name: $origin_country})
                MERGE (destination:Country {name: $destination_country})
                MERGE (s)-[:HAS_ROUTE_LEG]->(leg)
                MERGE (leg)-[:FROM]->(origin)
                MERGE (leg)-[:TO]->(destination)
                """,
                shipment_id=shipment.id,
                id=leg.id,
                sequence_number=leg.sequence_number,
                origin_country=leg.origin_country,
                destination_country=leg.destination_country,
                transport_mode=leg.transport_mode,
                carrier_name=leg.carrier_name,
            )

        for event in shipment.events:
            if event.consignment_id:
                target_id = event.consignment_id
                query = """
                MATCH (target:Consignment {id: $target_id})
                MERGE (event:ShipmentEvent {id: $id})
                SET event.eventType = $event_type,
                    event.locationCountry = $location_country,
                    event.occurredAt = $occurred_at
                MERGE (country:Country {name: $location_country})
                MERGE (event)-[:OCCURRED_IN]->(country)
                MERGE (event)-[:AFFECTS_CONSIGNMENT]->(target)
                """
            else:
                target_id = shipment.id
                query = """
                MATCH (target:Shipment {id: $target_id})
                MERGE (event:ShipmentEvent {id: $id})
                SET event.eventType = $event_type,
                    event.locationCountry = $location_country,
                    event.occurredAt = $occurred_at
                MERGE (country:Country {name: $location_country})
                MERGE (event)-[:OCCURRED_IN]->(country)
                MERGE (event)-[:AFFECTS_SHIPMENT]->(target)
                """
            tx.run(
                query,
                target_id=target_id,
                id=event.id,
                event_type=event.event_type,
                location_country=event.location_country,
                occurred_at=event.occurred_at.isoformat(),
            )

    @staticmethod
    def _write_domestic(tx, shipment):
        graph = build_domestic_graph(shipment)
        # Keep all projected domestic nodes under the owning shipment for idempotent replacement.
        tx.run("MATCH (n {projectionShipment: $shipment}) DETACH DELETE n", shipment=shipment.id)
        for node in graph.nodes:
            tx.run(
                f"CREATE (n:DomesticTwinNode:{node.type} "
                "{id: $id, label: $label, kind: $kind, projectionShipment: $shipment})",
                id=node.id,
                label=node.label,
                kind=node.type,
                shipment=shipment.id,
            )
        for edge in graph.edges:
            # Relationship names come exclusively from build_domestic_graph constants.
            tx.run(
                "MATCH (a:DomesticTwinNode {id: $source}), (b:DomesticTwinNode {id: $target}) "
                f"MERGE (a)-[:{edge.label}]->(b)",
                source=edge.source,
                target=edge.target,
            )

    @staticmethod
    def _delete_shipment(tx, shipment_id: str) -> None:
        tx.run("MATCH (n {projectionShipment: $shipment}) DETACH DELETE n", shipment=shipment_id)
        tx.run(
            """
            MATCH (shipment:Shipment {id: $shipment_id})
            OPTIONAL MATCH (shipment)-[:CONTAINS]->(consignment:Consignment)
            OPTIONAL MATCH (shipment)-[:HAS_ROUTE_LEG]->(leg:RouteLeg)
            WITH shipment,
                 collect(DISTINCT consignment) AS consignments,
                 collect(DISTINCT leg) AS legs
            OPTIONAL MATCH (shipmentEvent:ShipmentEvent)-[:AFFECTS_SHIPMENT]->(shipment)
            WITH shipment,
                 consignments,
                 legs,
                 collect(DISTINCT shipmentEvent) AS shipmentEvents
            OPTIONAL MATCH (consignmentEvent:ShipmentEvent)-[:AFFECTS_CONSIGNMENT]->
                (affectedConsignment:Consignment)
            WHERE affectedConsignment IN consignments
            WITH [shipment] + consignments + legs + shipmentEvents +
                collect(DISTINCT consignmentEvent) AS nodes
            UNWIND nodes AS node
            WITH node WHERE node IS NOT NULL
            DETACH DELETE node
            """,
            shipment_id=shipment_id,
        )


def load_graph_shipment(db: Session, shipment_id: str) -> Shipment | None:
    return (
        db.query(Shipment)
        .options(
            selectinload(Shipment.consignments),
            selectinload(Shipment.route_legs),
            selectinload(Shipment.events),
        )
        .filter(Shipment.id == shipment_id)
        .first()
    )


def build_graph_response(shipment: Shipment) -> ShipmentGraphRead:
    if shipment.domestic:
        return build_domestic_graph(shipment)
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    def add_node(node_id: str, label: str, node_type: str) -> None:
        nodes[node_id] = GraphNode(id=node_id, label=label, type=node_type)

    def add_edge(source: str, target: str, label: str) -> None:
        edge_id = f"{source}:{label}:{target}"
        edges[edge_id] = GraphEdge(id=edge_id, source=source, target=target, label=label)

    shipment_node = f"shipment:{shipment.id}"
    add_node(shipment_node, shipment.shipment_reference, "Shipment")

    add_country_nodes([shipment.exporter_country, shipment.importer_country], nodes)

    for consignment in shipment.consignments:
        consignment_node = f"consignment:{consignment.id}"
        add_node(
            consignment_node,
            f"{consignment.product_name} ({consignment.customs_status})",
            "Consignment",
        )
        origin_node = country_node_id(consignment.country_of_origin)
        destination_node = country_node_id(consignment.destination_country)
        add_country_nodes([consignment.country_of_origin, consignment.destination_country], nodes)
        add_edge(shipment_node, consignment_node, "CONTAINS")
        add_edge(consignment_node, origin_node, "ORIGINATES_IN")
        add_edge(consignment_node, destination_node, "DESTINED_FOR")

    for leg in sorted(shipment.route_legs, key=lambda item: item.sequence_number):
        leg_node = f"route-leg:{leg.id}"
        add_node(
            leg_node,
            f"Leg {leg.sequence_number}: {leg.origin_country} to {leg.destination_country}",
            "RouteLeg",
        )
        add_country_nodes([leg.origin_country, leg.destination_country], nodes)
        add_edge(shipment_node, leg_node, "HAS_ROUTE_LEG")
        add_edge(leg_node, country_node_id(leg.origin_country), "FROM")
        add_edge(leg_node, country_node_id(leg.destination_country), "TO")

    for event in shipment.events:
        event_node = f"event:{event.id}"
        add_node(event_node, event.event_type, "ShipmentEvent")
        add_country_nodes([event.location_country], nodes)
        add_edge(event_node, country_node_id(event.location_country), "OCCURRED_IN")
        if event.consignment_id:
            add_edge(event_node, f"consignment:{event.consignment_id}", "AFFECTS_CONSIGNMENT")
        else:
            add_edge(event_node, shipment_node, "AFFECTS_SHIPMENT")

    return ShipmentGraphRead(nodes=list(nodes.values()), edges=list(edges.values()))


def add_country_nodes(countries: Sequence[str], nodes: dict[str, GraphNode]) -> None:
    for country in countries:
        nodes[country_node_id(country)] = GraphNode(
            id=country_node_id(country), label=country, type="Country"
        )


def country_node_id(country: str) -> str:
    return f"country:{country.lower().replace(' ', '-')}"


def build_domestic_graph(shipment):
    nodes, edges = {}, {}

    def node(key, label, kind):
        nodes[key] = GraphNode(id=key, label=label, type=kind)
        return key

    def place(location):
        return node(
            f"location:{shipment.id}:{location['state']}:{location['pincode']}",
            f"{location['city']}, {location['state']} ({location['pincode']})",
            "Location",
        )

    def edge(source, target, label):
        key = f"{source}:{label}:{target}"
        edges[key] = GraphEdge(id=key, source=source, target=target, label=label)

    root = node(f"shipment:{shipment.id}", shipment.shipment_reference, "Shipment")
    origin = place(shipment.domestic["origin"])
    for item in shipment.consignments:
        key = node(
            f"consignment:{item.id}", f"{item.product_name} ({item.customs_status})", "Consignment"
        )
        edge(root, key, "CONTAINS")
        edge(key, origin, "ORIGINATES_IN")
        edge(key, place(item.domestic["destination"]), "DESTINED_FOR")
    for leg in shipment.route_legs:
        key = node(
            f"route-leg:{leg.id}",
            f"Leg {leg.sequence_number}: {leg.domestic['origin']['city']} "
            f"to {leg.domestic['destination']['city']}",
            "RouteLeg",
        )
        edge(root, key, "HAS_ROUTE_LEG")
        edge(key, place(leg.domestic["origin"]), "FROM")
        edge(key, place(leg.domestic["destination"]), "TO")
    for event in shipment.events:
        key = node(f"event:{event.id}", event.event_type, "ShipmentEvent")
        edge(key, place(event.event_metadata["location"]), "OCCURRED_IN")
        edge(
            key,
            f"consignment:{event.consignment_id}" if event.consignment_id else root,
            "AFFECTS_CONSIGNMENT" if event.consignment_id else "AFFECTS_SHIPMENT",
        )
    return ShipmentGraphRead(nodes=list(nodes.values()), edges=list(edges.values()))
