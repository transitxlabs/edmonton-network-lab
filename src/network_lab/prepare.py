"""Join official census data and compile a City road walking proxy."""

from __future__ import annotations

import csv
import io
import json
import math
import time
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree
from shapely import STRtree, make_valid
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import nearest_points, transform

from .common import ROOT, digest, space_guard, write_json
from .engine import write_model
from .gtfs import load, occurrences


def census(frozen: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with zipfile.ZipFile(frozen / "98100015.zip") as z:
        rows = list(csv.DictReader(io.TextIOWrapper(z.open("98100015.csv"), encoding="utf-8-sig")))
    population_key = "Population and dwelling counts (5): Population, 2021 [1]"
    inside = False
    city_population = -1
    members: dict[str, int] = {}
    # The official CSV is a hierarchy traversal: DA rows immediately follow their CSD.
    # Reconcile every member and their sum to the named CSD control total.
    for r in rows:
        if not r["DGUID"].startswith("2021S0512"):
            inside = r["DGUID"] == "2021A00054811061"
            if inside:
                city_population = int(r[population_key])
        elif inside:
            members[r["DGUID"]] = int(r[population_key])
    if sum(members.values()) != city_population or city_population <= 0:
        raise ValueError("Census hierarchy fails the City population reconciliation")
    boundaries = json.loads((frozen / "boundaries.json").read_text())
    by_id = {r["dguid"]: r for r in boundaries if r.get("dguid") in members}
    missing = sorted(set(members) - set(by_id))
    if missing:
        raise ValueError(f"Missing official DA boundaries: {missing}")
    result = []
    repairs = []
    projector = Transformer.from_crs(4326, 26912, always_xy=True).transform
    inverse = Transformer.from_crs(26912, 4326, always_xy=True).transform
    for dguid, pop in sorted(members.items()):
        r = by_id[dguid]
        geometry = shape(r["the_geom"])
        if not geometry.is_valid:
            repairs.append(dguid)
            geometry = make_valid(geometry)
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"Invalid DA polygon: {dguid}")
        # Interior representative point in a metric projection, never an outside centroid.
        point = transform(inverse, transform(projector, geometry).representative_point())
        result.append(
            {
                "id": dguid,
                "population": pop,
                "lon": point.x,
                "lat": point.y,
                "geometry": mapping(geometry),
            }
        )
    return result, {
        "city_dguid": "2021A00054811061",
        "dissemination_areas": len(result),
        "population": city_population,
        "missing_boundaries": missing,
        "polygon_repairs": repairs,
        "polygon_repair_method": "make_valid; population and membership unchanged",
        "representative_point": "interior point in EPSG:26912",
    }


def largest_component_segments(
    segments: list[tuple[int, int, float]], node_count: int
) -> tuple[list[int], int]:
    """Select road segments in the largest weak component before point connectors."""
    a, b, _ = zip(*segments)
    graph = csr_matrix((np.ones(len(a)), (a, b)), shape=(node_count, node_count))
    count, labels = connected_components(graph, directed=True, connection="weak")
    largest = int(np.argmax(np.bincount(labels)))
    return [i for i, (a, b, _) in enumerate(segments) if labels[a] == largest], int(count)


def walking_failures(
    points: list[dict[str, Any]], walks: list[np.ndarray], snaps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Inventory populated areas lacking connectors or another reachable area."""
    populated = {i for i, p in enumerate(points) if p.get("population", 0) > 0}
    return [
        {
            "id": points[i]["id"],
            "population": points[i]["population"],
            "reason": (
                "no largest-component connector within 300 m"
                if not snaps[i]["connected"]
                else "only own populated area reachable by walking in 60 minutes"
            ),
        }
        for i in sorted(populated)
        if not snaps[i]["connected"]
        or not any(
            int(j) in populated and int(j) != i and seconds <= 3600 for j, seconds in walks[i]
        )
    ]


def check_walking_islands(
    points: list[dict[str, Any]],
    walks: list[np.ndarray],
    snaps: list[dict[str, Any]] | None = None,
    exceptions: list[dict[str, Any]] | None = None,
) -> None:
    """Require the exact frozen exception set, including populations and reasons."""
    snaps = snaps if snaps is not None else [{"connected": True} for _ in points]
    actual = walking_failures(points, walks, snaps)
    if actual != (exceptions or []):
        raise ValueError(
            "Populated areas with only their own 60-minute walking reach or no connector "
            f"differ from frozen exceptions: {actual}"
        )


def walking(
    points: list[dict[str, Any]],
    feed: dict[str, Any],
    frozen: Path,
    manifests: Path,
    *,
    discover_exceptions: bool = False,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    speed = 1.33
    projector = Transformer.from_crs(4326, 26912, always_xy=True).transform
    rows = json.loads((frozen / "roads_selected.json").read_text())
    nodes: dict[str, int] = {}
    lines: list[Any] = []
    segments: list[tuple[int, int, float]] = []
    edges: dict[tuple[int, int], int] = {}
    excluded: list[dict[str, str]] = []
    # Join an endpoint without an intersection identifier to an identified
    # junction only within two metres. Distinct identified junctions stay distinct.
    known: dict[str, tuple[float, float]] = {}
    for r in rows:
        coords = r.get("geometry", {}).get("coordinates", [])
        if r.get("centerline_type") not in ("Road", "Alley") or len(coords) < 2:
            continue
        for field, coord in zip(
            ("from_intersectionid", "to_intersectionid"), (coords[0], coords[-1])
        ):
            if r.get(field):
                known.setdefault(r[field], projector(*coord))
    known_ids = sorted(known)
    known_tree = cKDTree([known[k] for k in known_ids])
    endpoint_joins = 0

    def node(key: str) -> int:
        if key not in nodes:
            nodes[key] = len(nodes)
        return nodes[key]

    def edge(a: int, b: int, cost: int, bidirectional: bool = True) -> None:
        edges[a, b] = min(edges.get((a, b), 1_000_000_000), max(0, cost))
        if bidirectional:
            edges[b, a] = min(edges.get((b, a), 1_000_000_000), max(0, cost))

    for r in rows:
        reason = ""
        classification = r.get("functional_class_code", "")
        if r.get("centerline_type") not in ("Road", "Alley"):
            reason = "not road or alley"
        elif classification == "Local-Private":
            reason = "private road"
        elif any(label in classification.lower() for label in ("freeway", "expressway")):
            reason = "explicit limited-access freeway or expressway"
        if reason:
            excluded.append({"id": r["centerlineid"], "reason": reason})
            continue
        geom = transform(projector, shape(r["geometry"]))
        if not isinstance(geom, LineString) or geom.is_empty or geom.length <= 0:
            excluded.append({"id": r["centerlineid"], "reason": "invalid or empty line"})
            continue
        coords = list(geom.coords)
        keys = []
        for name, coord in zip(
            ("from_intersectionid", "to_intersectionid"), (coords[0], coords[-1])
        ):
            key = r.get(name)
            if not key:
                distance, neighbour = known_tree.query(coord)
                if distance <= 2:
                    key = known_ids[int(neighbour)]
                    endpoint_joins += 1
                else:
                    key = f"xy:{coord[0]:.1f}:{coord[1]:.1f}"
            keys.append(key)
        a, b = node(keys[0]), node(keys[1])
        edge(a, b, math.ceil(geom.length / speed))
        lines.append(geom)
        segments.append((a, b, geom.length))
    base_nodes = len(nodes)
    if not lines:
        raise ValueError("No usable road edges")
    selected, road_components = largest_component_segments(segments, base_nodes)
    tree = STRtree([lines[i] for i in selected])
    inverse = Transformer.from_crs(26912, 4326, always_xy=True).transform
    snap_ledger = []
    npoints = len(points)
    for i, p in enumerate(points):
        geom = Point(*projector(p["lon"], p["lat"]))
        seg = selected[int(tree.nearest(geom))]
        line = lines[seg]
        distance = geom.distance(line)
        original_distance = distance
        moved_metres = 0.0
        access_point = geom
        if distance > 300 and p["kind"] == "dissemination_area":
            polygon = transform(projector, shape(p["geometry"]))
            candidate_seg = selected[int(tree.nearest(polygon))]
            candidate_line = lines[candidate_seg]
            candidate, _ = nearest_points(polygon, candidate_line)
            if candidate.distance(candidate_line) <= 300:
                access_point = candidate
                moved_metres = geom.distance(candidate)
                seg, line = candidate_seg, candidate_line
                distance = candidate.distance(candidate_line)
        access_wgs84 = transform(inverse, access_point)
        moved = access_point != geom
        if p["kind"] == "dissemination_area":
            p["access_point"] = {
                "lon": access_wgs84.x,
                "lat": access_wgs84.y,
                "moved": moved,
                "moved_metres": moved_metres,
                "added_walking_seconds": math.ceil(moved_metres / speed),
                "connector_metres": distance,
            }
        snap_ledger.append(
            {
                "id": p["id"],
                "kind": p["kind"],
                "snap_metres": distance,
                "connected": distance <= 300,
                "target": "largest road component",
                "road_segment_index": seg,
                "original_snap_metres": original_distance,
                "original_point": {"lon": p["lon"], "lat": p["lat"]},
                "access_point": {"lon": access_wgs84.x, "lat": access_wgs84.y},
                "moved": moved,
                "moved_metres": moved_metres,
                "added_walking_seconds": math.ceil(moved_metres / speed),
            }
        )
        if distance <= 300:
            a, b, length = segments[seg]
            along = line.project(access_point)
            added = math.ceil(moved_metres / speed)
            edge(base_nodes + i, a, added + math.ceil((distance + along) / speed))
            edge(base_nodes + i, b, added + math.ceil((distance + length - along) / speed))
    si = feed["stop_index"]
    pathway_count = 0
    pathway_imputations = []
    for p in feed["tables"].get("pathways", []):
        a, b = si[p["from_stop_id"]], si[p["to_stop_id"]]
        if p.get("traversal_time"):
            seconds = int(p["traversal_time"])
        elif p.get("length"):
            seconds = max(1, math.ceil(float(p["length"]) / speed))
        else:
            pa, pb = points[a], points[b]
            ax, ay = projector(pa["lon"], pa["lat"])
            bx, by = projector(pb["lon"], pb["lat"])
            seconds = max(1, math.ceil(math.hypot(ax - bx, ay - by) / speed))
            pathway_imputations.append(
                {
                    "id": p["pathway_id"],
                    "seconds": seconds,
                    "method": "horizontal endpoint distance; minimum one second",
                }
            )
        edge(base_nodes + a, base_nodes + b, seconds, p["is_bidirectional"] == "1")
        pathway_count += 1
    ii, jj, ww = zip(*[(a, b, w) for (a, b), w in sorted(edges.items())])
    graph = csr_matrix(
        (np.asarray(ww, dtype=np.float64), (ii, jj)),
        shape=(base_nodes + npoints, base_nodes + npoints),
    )
    components, labels = connected_components(graph, directed=True, connection="weak")
    walks: list[np.ndarray] = []
    t0 = time.perf_counter()
    for begin in range(0, npoints, 24):
        space_guard()
        ids = np.arange(base_nodes + begin, base_nodes + min(npoints, begin + 24))
        distances = dijkstra(graph, directed=True, indices=ids, limit=3600)[:, base_nodes:]
        for ds in distances:
            reachable = np.flatnonzero(ds <= 3600)
            walks.append(np.column_stack((reachable, ds[reachable])).astype(np.int32))
        if begin % 480 == 0:
            print(f"Walking closure {begin}/{npoints}, {time.perf_counter() - t0:.1f}s", flush=True)
    populated = {i for i, p in enumerate(points) if p.get("population", 0) > 0}
    islands = [
        i
        for i in sorted(populated)
        if not any(int(j) in populated and int(j) != i and cost <= 3600 for j, cost in walks[i])
    ]
    failures = walking_failures(points, walks, snap_ledger)
    exception_path = manifests / "walking_exceptions.json"
    registration_path = manifests / "walking_exceptions_registration.json"
    exceptions = []
    exception_hash = None
    if exception_path.exists() and not discover_exceptions:
        exception_hash = digest(exception_path)
        registration = json.loads(registration_path.read_text())
        if exception_hash != registration["sha256"]:
            raise ValueError("Frozen walking exceptions differ from registration")
        exceptions = json.loads(exception_path.read_text())["areas"]
    matched = failures == exceptions and not discover_exceptions
    moved_areas = [
        p for p in points if p["kind"] == "dissemination_area" and p["access_point"]["moved"]
    ]
    write_json(manifests / "walking_snaps.json", snap_ledger)
    write_json(
        manifests / "walking_validation.json",
        {
            "status": "passed" if matched else "discovery" if discover_exceptions else "failed",
            "populated_area_count": len(populated),
            "walking_only_self_count": len(islands),
            "maximum_connector_metres": 300,
            "connector_target": "largest road component",
            "failures": failures,
            "exception_sha256": exception_hash,
            "moved_area_count": len(moved_areas),
            "moved_area_population": sum(p["population"] for p in moved_areas),
            "islands": [
                {
                    "id": points[i]["id"],
                    "population": points[i]["population"],
                    "connected": snap_ledger[i]["connected"],
                    "snap_metres": snap_ledger[i]["snap_metres"],
                }
                for i in islands
            ],
        },
    )
    if not discover_exceptions:
        check_walking_islands(points, walks, snap_ledger, exceptions)
    overrides: dict[tuple[int, int], int | None] = {}
    for r in feed["tables"].get("transfers", []):
        a, b = si[r["from_stop_id"]], si[r["to_stop_id"]]
        if r["transfer_type"] == "3":
            overrides[a, b] = None
        elif r["transfer_type"] == "2":
            overrides[a, b] = int(r["min_transfer_time"])
        elif r["transfer_type"] not in ("0", "1"):
            raise ValueError("Unsupported transfer type")
    board_walks = []
    for a in range(len(feed["stops"])):
        adjusted = []
        for b, seconds in walks[a]:
            b = int(b)
            if b >= len(feed["stops"]):
                continue
            rule = overrides.get((a, b), 0)
            if rule is not None:
                cost = max(int(seconds), rule)
                if cost <= 3600:
                    adjusted.append((b, cost))
        board_walks.append(np.asarray(adjusted, dtype=np.int32).reshape(-1, 2))
    write_json(manifests / "walking_snaps.json", snap_ledger)
    write_json(manifests / "pathway_imputations.json", pathway_imputations)
    write_json(manifests / "walking_excluded.json", excluded)
    write_json(
        manifests / "walking.json",
        {
            "source": "City of Edmonton Road Network",
            "proxy": True,
            "speed_metres_per_second": speed,
            "maximum_snap_metres": 300,
            "snap_target": "largest road component before connectors and station pathways",
            "road_components_before_connectors": road_components,
            "populated_walking_only_self_areas": len(islands),
            "moved_access_areas": len(moved_areas),
            "moved_access_population": sum(p["population"] for p in moved_areas),
            "exceptions": failures,
            "access_point_rule": "If the interior point has no connector within 300 m, use the nearest point of its official polygon within 300 m of the largest component; add straight original-to-access walking at 1.33 m/s on access and egress; keep the original point.",
            "arterial_rule": "Keep arterials except explicit freeway or expressway labels. Source fields do not identify limited access; all arterial classes are retained.",
            "road_records": len(rows),
            "included_segments": len(lines),
            "excluded_segments": len(excluded),
            "graph_nodes": graph.shape[0],
            "directed_edges": graph.nnz,
            "components": int(components),
            "pathways": pathway_count,
            "unidentified_endpoint_joins_within_two_metres": endpoint_joins,
            "unconnected_points": dict(
                Counter(x["kind"] for x in snap_ledger if not x["connected"])
            ),
            "closure_edges": sum(len(x) for x in walks),
            "closure_seconds": 3600,
            "component_size_max": int(np.max(np.bincount(labels))),
            "method": "Road endpoint identifiers; line projection connectors; integer-ceiling edge seconds; directed pathways",
            "limits": "Road centrelines approximate walking. Crossings, sidewalks, barriers, entrances and accessibility are not certified.",
        },
    )
    return walks, board_walks


def prepare(root: Path = ROOT, *, discover_exceptions: bool = False) -> dict[str, Any]:
    space_guard()
    frozen, manifests = root / "data/frozen", root / "data/manifests"
    feed = load(frozen / "ets_gtfs.zip", manifests)
    das, control = census(frozen)
    write_json(manifests / "census.json", control)
    points = [
        {
            "id": s["stop_id"],
            "kind": "stop",
            "lon": float(s["stop_lon"]),
            "lat": float(s["stop_lat"]),
        }
        for s in feed["stops"]
    ]
    points.extend({**d, "kind": "dissemination_area"} for d in das)
    libraries = json.loads((frozen / "libraries.json").read_text())
    for r in sorted(libraries, key=lambda x: x["branch_id"]):
        points.append(
            {
                "id": "library:" + r["branch_id"],
                "name": r["branch"],
                "kind": "library",
                "lon": float(r["longitude"]),
                "lat": float(r["latitude"]),
            }
        )
    walks, board_walks = walking(
        points, feed, frozen, manifests, discover_exceptions=discover_exceptions
    )
    if discover_exceptions:
        return json.loads((manifests / "walking_validation.json").read_text())
    trips, ids = occurrences(feed, date(2026, 10, 13))
    write_model(
        root / "build/model.bin",
        len(feed["stops"]),
        len(points),
        len(feed["routes"]),
        walks,
        board_walks,
        trips,
    )
    metadata = {
        "service_date": "2026-10-13",
        "timezone": "America/Edmonton",
        "nstops": len(feed["stops"]),
        "nda": len(das),
        "npoints": len(points),
        "nroutes": len(feed["routes"]),
        "trip_occurrences": len(trips),
        "routes": feed["routes"],
        "trip_ids": ids,
        "points": points,
        "model_sha256": digest(root / "build/model.bin"),
    }
    write_json(manifests / "model.json", metadata)
    return metadata
