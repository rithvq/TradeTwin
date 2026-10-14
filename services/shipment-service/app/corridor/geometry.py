"""Exact topology or real polygon intersection; bounding boxes never prove an impact."""

import math

from shapely.geometry import LineString, shape


def validate_geometry(value):
    if value.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Only Polygon/MultiPolygon source geometry is supported")
    count = 0

    def visit(node, depth=0):
        nonlocal count
        if depth > 8 or not isinstance(node, list):
            raise ValueError("Invalid or excessively nested geometry")
        if node and isinstance(node[0], int | float):
            count += 1
            if (
                count > 10000
                or len(node) != 2
                or not all(math.isfinite(n) for n in node)
                or not (-180 <= node[0] <= 180 and -90 <= node[1] <= 90)
            ):
                raise ValueError("Geometry exceeds vertex/coordinate bounds")
        else:
            for child in node:
                visit(child, depth + 1)

    visit(value.get("coordinates"))
    geometry = shape(value)
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("Source polygon is empty or invalid")
    return geometry


def match(section, geography):
    kind = geography["geometry_kind"]
    if kind == "ROAD_EDGE_SET":
        if geography["dataset_revision_id"] != section["dataset_revision_id"]:
            return (
                "POSSIBLE_MATCH"
                if not geography["state_codes"]
                or set(geography["state_codes"]) & set(section["state_codes"])
                else "NONE"
            )
        return "EXACT_EDGE" if section["edge_key"] in geography["edge_keys"] else "NONE"
    if kind in {"POLYGON", "MULTIPOLYGON"}:
        if not section.get("coordinates"):
            return "POSSIBLE_MATCH"
        return (
            "GEOMETRY_INTERSECTION"
            if validate_geometry(geography["geojson"]).intersects(
                LineString(section["coordinates"])
            )
            else "NONE"
        )
    if kind == "DISTRICT":
        if not section.get("district_codes"):
            return (
                "POSSIBLE_MATCH"
                if not geography["state_codes"]
                or set(geography["state_codes"]) & set(section["state_codes"])
                else "NONE"
            )
        return (
            "ADMIN_AREA"
            if set(geography["district_codes"]) & set(section["district_codes"])
            else "NONE"
        )
    if kind == "STATE":
        return (
            "ADMIN_AREA" if set(geography["state_codes"]) & set(section["state_codes"]) else "NONE"
        )
    return (
        "POSSIBLE_MATCH"
        if not geography["state_codes"]
        or set(geography["state_codes"]) & set(section["state_codes"])
        else "NONE"
    )
