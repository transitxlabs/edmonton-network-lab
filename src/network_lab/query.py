"""Offline what-if query for one dissemination area and any service-day minute."""

from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np

from .common import ROOT, space_guard
from .engine import Engine, compile_engine, delete_service
from .gtfs import seconds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="2021 dissemination-area DGUID")
    parser.add_argument(
        "--departure", required=True, help="Local service-day HH:MM, 05:00 to 24:00"
    )
    parser.add_argument(
        "--remove-route", action="append", default=[], help="Published route identifier"
    )
    args = parser.parse_args()
    space_guard()
    try:
        depart = seconds(args.departure + ":00")
    except ValueError:
        parser.error("Departure must use HH:MM with valid hours and minutes")
    if not 18000 <= depart <= 86400:
        parser.error("Departure must be from 05:00 through 24:00")
    metadata = ROOT / "data/manifests/model.json"
    if not (ROOT / "build/model.bin").exists():
        parser.error("Rebuild the frozen inputs first with ./rebuild.sh")
    meta = json.loads(metadata.read_text())
    ns, nda = meta["nstops"], meta["nda"]
    areas = meta["points"][ns : ns + nda]
    indices = {p["id"]: ns + i for i, p in enumerate(areas)}
    if args.origin not in indices:
        parser.error("Origin is not a City dissemination area in the frozen input")
    route_ids = {r["route_id"]: i for i, r in enumerate(meta["routes"])}
    unknown = sorted(set(args.remove_route) - set(route_ids))
    if unknown:
        parser.error(f"Unknown published route identifiers: {unknown}")
    removed = {route_ids[r] for r in args.remove_route}
    library = ROOT / "build/libnetwork.dylib"
    if not library.exists():
        library = compile_engine()
    origin = indices[args.origin]
    base = Engine(ROOT / "build/model.bin", meta["npoints"], meta["nroutes"], library)
    try:
        original, support, _ = base.query(origin, depart)
        reused = not any(support[r] for r in removed)
        if removed and not reused:
            key = hashlib.sha256(",".join(map(str, sorted(removed))).encode()).hexdigest()[:16]
            target = ROOT / f"build/scenarios/{key}.bin"
            delete_service(ROOT / "build/model.bin", target, set(), removed)
            reduced = Engine(target, meta["npoints"], meta["nroutes"], library)
            try:
                changed, _, _ = reduced.query(origin, depart)
            finally:
                reduced.close()
        else:
            changed = original
    finally:
        base.close()
    assert np.all(changed[ns:] >= original[ns:])
    population = np.array([p["population"] for p in areas], dtype=np.int64)
    answer = {
        "origin": args.origin,
        "service_date": meta["service_date"],
        "departure_seconds": depart,
        "removed_routes": sorted(set(args.remove_route)),
        "surviving_certificate_reused": reused,
        "scope": "Frozen schedule and walking proxy",
    }
    metrics = []
    for threshold in [1800, 2700, 3600]:
        old = original[ns:] - depart
        new = changed[ns:] - depart
        before_pop = int(population[old[:nda] <= threshold].sum())
        after_pop = int(population[new[:nda] <= threshold].sum())
        metrics.append(
            {
                "threshold_minutes": threshold // 60,
                "base_population": before_pop,
                "changed_population": after_pop,
                "population_lost": before_pop - after_pop,
                "base_libraries": int((old[nda:] <= threshold).sum()),
                "changed_libraries": int((new[nda:] <= threshold).sum()),
            }
        )
    answer["access"] = metrics
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
