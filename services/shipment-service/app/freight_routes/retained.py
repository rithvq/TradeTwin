"""Bounded alternatives from an explicitly selected published topology; never a live fallback."""

from decimal import Decimal
from itertools import islice

import networkx as nx

from app.freight.routing import path_snapshot
from app.operations.access import fail
from app.trades.reference import STATES
from app.trades.terms import digest


def alternatives(snapshot):
    dataset = snapshot["dataset"]
    data = dataset["data"]
    nodes = {n["node_key"]: n for n in data["nodes"]}
    graph = nx.DiGraph()
    for edge in data["edges"]:
        graph.add_edge(
            edge["from_node_key"],
            "edge:" + edge["edge_key"],
            distance=edge["distance_meters"],
            duration=edge["estimated_driving_seconds"],
        )
        graph.add_edge("edge:" + edge["edge_key"], edge["to_node_key"], distance=0, duration=0)
        if not edge["directed"]:
            graph.add_edge(
                edge["to_node_key"],
                "reverse:" + edge["edge_key"],
                distance=edge["distance_meters"],
                duration=edge["estimated_driving_seconds"],
            )
            graph.add_edge(
                "reverse:" + edge["edge_key"], edge["from_node_key"], distance=0, duration=0
            )

    def gate(pin, kind):
        matching = [
            key
            for key, node in nodes.items()
            if node["node_kind"] == kind
            and abs(float(node["longitude"]) - pin["coordinates"][0]) < 1e-7
            and abs(float(node["latitude"]) - pin["coordinates"][1]) < 1e-7
            and node["state_code"] == pin["state_code"]
        ]
        if len(matching) != 1:
            fail(
                "ROUTING_INPUT_MISSING",
                "The retained topology does not contain the exact confirmed gates.",
            )
        return matching[0]

    first, last = gate(snapshot["pickup"], "PICKUP_ACCESS"), gate(snapshot["drop"], "DROP_ACCESS")
    truck = snapshot["truck"]
    profile = {
        "combined_tare_weight_kg": truck["tare_kg"],
        "overall_height_mm": Decimal(truck["height_m"]) * 1000,
        "overall_width_mm": Decimal(truck["width_m"]) * 1000,
        "overall_length_mm": Decimal(truck["length_m"]) * 1000,
        "maximum_actual_axle_load_kg": truck["axle_load_kg"],
        "supported_cargo_profile_codes": ["ORDINARY_GOODS"],
    }
    # Do not infer truck capabilities from what the road happens to permit.
    profile["supported_cargo_profile_codes"] = snapshot.get("profile_codes", [])
    output = {}
    edges = {e["edge_key"]: e for e in data["edges"]}
    for objective in ("distance", "duration"):
        try:
            paths = islice(nx.shortest_simple_paths(graph, first, last, weight=objective), 3)
            for path in paths:
                route_nodes = [key for key in path if not key.startswith(("edge:", "reverse:"))]
                keys = [
                    key.split(":", 1)[1] for key in path if key.startswith(("edge:", "reverse:"))
                ]
                template = {
                    "ordered_node_keys": route_nodes,
                    "ordered_edge_keys": keys,
                    "dataset_revision_id": dataset["id"],
                }
                route = path_snapshot(
                    data, template, profile, {"gross_weight_kg": snapshot["cargo_weight_kg"]}
                )
                if not profile["supported_cargo_profile_codes"]:
                    failures = [n for n in route["restriction_notices"] if n["outcome"] == "FAIL"]
                    if all(n["code"] == "VEHICLE_PROFILE_UNSUPPORTED" for n in failures):
                        route["restriction_assessment"] = "UNKNOWN"
                geometry, true_geometry = [], True
                for index, key in enumerate(keys):
                    edge = edges[key]
                    coords = (edge.get("geometry") or {}).get("coordinates")
                    if not coords:
                        true_geometry = False
                        coords = [
                            [
                                float(nodes[route_nodes[index]]["longitude"]),
                                float(nodes[route_nodes[index]]["latitude"]),
                            ],
                            [
                                float(nodes[route_nodes[index + 1]]["longitude"]),
                                float(nodes[route_nodes[index + 1]]["latitude"]),
                            ],
                        ]
                    elif edge["from_node_key"] != route_nodes[index]:
                        coords = list(reversed(coords))
                    geometry.extend(coords if not geometry else coords[1:])
                sequence = route["state_sequence"] or []
                ident = "retained-" + digest(keys)[:20]
                output[ident] = {
                    "id": ident,
                    "label": "Retained " + objective + " alternative",
                    "geometry": {"type": "LineString", "coordinates": geometry},
                    "geometry_kind": "ROAD_GEOMETRY" if true_geometry else "TOPOLOGICAL_SCHEMATIC",
                    "distance_m": route["distance_meters"],
                    "driving_seconds": route["estimated_driving_seconds"],
                    "major_road_metres": None,
                    "toll_road_metres": None,
                    "road_exposure": None,
                    "road_names": [],
                    "provider_warning_codes": [],
                    "retained_assessment": route["restriction_assessment"],
                    "sections": {
                        "dataset": data,
                        "route": {**template, "state_sequence": sequence},
                    },
                    "corridor": {
                        "state_sequence": sequence,
                        "state_names": [STATES.get(s, s) for s in sequence],
                        "mapping_status": "RETAINED_TOPOLOGY",
                        "state_outlines": [],
                        "boundaries": {
                            "name": data["source_reference"],
                            "status": "RETAINED_REFERENCE",
                        },
                    },
                    "provider": {
                        "name": data["source_kind"],
                        "url": data.get("source_reference"),
                        "attribution": data["attribution_text"],
                        "traffic": "RETAINED_ESTIMATE_NOT_LIVE_TRAFFIC",
                    },
                }
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
    return list(output.values()), []
