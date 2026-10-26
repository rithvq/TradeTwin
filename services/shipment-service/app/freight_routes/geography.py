"""Ordered polygon intersections, including state re-entry; no state-centroid guessing."""

import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

from shapely.geometry import LineString, Point, mapping, shape
from shapely.strtree import STRtree

from app.operations.access import fail
from app.trades.reference import STATES
from app.trades.terms import digest

from .network import document

ENDPOINT = "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/"
HOSTS = {
    "www.geoboundaries.org",
    "geoboundaries.org",
    "github.com",
    "raw.githubusercontent.com",
    "media.githubusercontent.com",
}
_cache = {}
_lock = threading.Lock()


def normal(value):
    latin = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", latin.lower().replace("&", "and"))


def state_code(properties):
    if properties.get("state_code") in STATES:
        return properties["state_code"]
    aliases = {
        "nctofdelhi": "07",
        "nationalcapitalterritoryofdelhi": "07",
        "orissa": "21",
        "pondicherry": "34",
        "dadraandnagarhaveli": "26",
        "damananddiu": "26",
    }
    names = {normal(name): code for code, name in STATES.items()}
    return {**names, **aliases}.get(normal(properties.get("shapeName", properties.get("name", ""))))


def prepare(data, provenance):
    features = data.get("features", [])
    if data.get("type") != "FeatureCollection" or not 1 <= len(features) <= 100:
        fail("BOUNDARIES_INVALID", "The state boundary dataset is invalid.")
    geometries, codes, labels = [], [], []
    for feature in features:
        geometry = shape(feature["geometry"])
        if (
            geometry.geom_type not in {"Polygon", "MultiPolygon"}
            or geometry.is_empty
            or not geometry.is_valid
        ):
            fail("BOUNDARIES_INVALID", "State boundaries must be valid polygons.")
        geometries.append(geometry)
        codes.append(state_code(feature.get("properties", {})))
        labels.append(
            str(
                feature.get("properties", {}).get(
                    "shapeName", feature.get("properties", {}).get("name", "Unknown")
                )
            )
        )
    return {
        "geometries": geometries,
        "codes": codes,
        "labels": labels,
        "tree": STRtree(geometries),
        "provenance": provenance,
        "hash": digest(data),
    }


def load(client):
    local = os.getenv("FREIGHT_STATE_BOUNDARIES_FILE")
    key = (
        local or ENDPOINT,
        Path(local).stat().st_mtime_ns if local and Path(local).exists() else None,
    )
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 21600:
            return cached[1]
    if local:
        path = Path(local)
        if not path.is_file() or path.stat().st_size > 30_000_000:
            fail("BOUNDARIES_INVALID", "Configure a bounded GeoJSON state-boundary file.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            fail("BOUNDARIES_INVALID", "The configured state-boundary file could not be read.")
        provenance = {
            "name": "Configured state boundary reference",
            "url": None,
            "year": data.get("year"),
            "attribution": data.get("attribution", "Configured reference"),
            "status": "CONFIGURED_REFERENCE_REQUIRES_REVIEW",
        }
    else:
        meta = document(client, "GET", ENDPOINT, hosts=HOSTS, limit=200000)
        url = meta.get("simplifiedGeometryGeoJSON", "")
        if not url.startswith("https://github.com/wmgeolab/geoBoundaries/raw/"):
            fail("BOUNDARIES_INVALID", "The boundary provider returned an unapproved download.")
        data = document(client, "GET", url, hosts=HOSTS, limit=30_000_000)
        provenance = {
            "name": "geoBoundaries India ADM1 reference",
            "url": ENDPOINT,
            "year": meta.get("boundaryYearRepresented"),
            "attribution": meta.get("boundarySource", "geoBoundaries")
            + "; "
            + meta.get("boundaryLicense", ""),
            "status": "THIRD_PARTY_REFERENCE_REQUIRES_REVIEW",
        }
    value = prepare(data, provenance)
    with _lock:
        _cache.clear()
        _cache[key] = (time.monotonic(), value)
    return value


def corridor(coords, boundaries):
    ordered, unknown, used = [], False, set()
    for first, last in zip(coords, coords[1:], strict=False):
        segment = LineString([first, last])
        if segment.length == 0:
            continue
        indexes = list(boundaries["tree"].query(segment))
        cuts = {0.0, 1.0}
        for index in indexes:
            intersection = segment.intersection(boundaries["geometries"][index].boundary)
            pieces = list(intersection.geoms) if hasattr(intersection, "geoms") else [intersection]
            for piece in pieces:
                if piece.geom_type == "Point":
                    cuts.add(segment.project(piece, normalized=True))
                elif piece.geom_type == "LineString" and not piece.is_empty:
                    cuts.update(
                        segment.project(Point(p), normalized=True)
                        for p in (piece.coords[0], piece.coords[-1])
                    )
        cuts = sorted(cuts)
        for start, end in zip(cuts, cuts[1:], strict=False):
            if end - start < 1e-10:
                continue
            midpoint = segment.interpolate((start + end) / 2, normalized=True)
            matches = [
                index for index in indexes if boundaries["geometries"][index].covers(midpoint)
            ]
            codes = {boundaries["codes"][i] for i in matches}
            code = next(iter(codes)) if len(codes) == 1 else None
            unknown = unknown or code is None
            used.update(matches)
            if not ordered or ordered[-1] != code:
                ordered.append(code)
    return {
        "state_sequence": ordered,
        "state_names": [STATES.get(code, "Unresolved boundary interval") for code in ordered],
        "mapping_status": "PARTIAL" if unknown or not ordered else "MAPPED_REFERENCE",
        "boundaries": {**boundaries["provenance"], "fingerprint_short": boundaries["hash"][:12]},
        "state_outlines": [
            {
                "state_code": boundaries["codes"][i],
                "name": boundaries["labels"][i],
                "geometry": mapping(
                    boundaries["geometries"][i].simplify(0.01, preserve_topology=True)
                ),
            }
            for i in sorted(used)
        ],
    }
