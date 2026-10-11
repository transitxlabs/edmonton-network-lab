"""Alternating-trip reductions checked against surviving certificates and connection scan."""

import csv
import hashlib
import json
import struct
import time
from collections import defaultdict

import numpy as np

from network_lab.common import ROOT, digest, space_guard, write_json
from network_lab.engine import Engine, certificate_survives, delete_service


def frequency_checks():
    space_guard()
    meta = json.loads((ROOT / "data/manifests/model.json").read_text())
    design = json.loads((ROOT / "results/design.json").read_text())
    model = ROOT / "build/model.bin"
    library = ROOT / "build/libnetwork.dylib"
    patterns = defaultdict(list)
    with model.open("rb") as f:
        _, ns, np_, _, nt = struct.unpack("<5i", f.read(20))
        for _ in range(ns + np_):
            count = struct.unpack("<i", f.read(4))[0]
            f.seek(count * 8, 1)
        for t in range(nt):
            route, count = struct.unpack("<2i", f.read(8))
            rows = np.frombuffer(f.read(count * 20), dtype="<i4").reshape(-1, 5)
            if meta["trip_ids"][t].startswith(meta["service_date"] + ":"):
                pattern = route, tuple((int(r[0]), int(r[3]), int(r[4])) for r in rows)
                patterns[pattern].append((int(rows[0, 2]), t))
    deletions = defaultdict(set)
    for (route, _), group in patterns.items():
        if len(group) >= 2:
            deletions[route].update(t for _, t in sorted(group)[::2])
    support = np.load(ROOT / "results/arrays/route_support.npy", mmap_mode="r")
    candidates = sorted(
        r for r, deleted in deletions.items() if len(deleted) >= 2 and support[:, r].sum() >= 4
    )
    rng = np.random.default_rng(20261012)
    selected = rng.choice(candidates, size=min(20, len(candidates)), replace=False).tolist()
    assert len(selected) == 20
    base = Engine(model, meta["npoints"], meta["nroutes"], library)
    records, ledger = [], []
    t0 = time.perf_counter()
    try:
        for case, route in enumerate(selected):
            space_guard()
            deleted = deletions[route]
            # Cases are sequential and each model closes before the next replacement.
            # Keep hashes in the ledger while retaining only one scratch model.
            target = ROOT / "work-tmp.noindex/frequency-current.bin"
            target.parent.mkdir(parents=True, exist_ok=True)
            deletion = delete_service(model, target, deleted)
            changed = Engine(target, meta["npoints"], meta["nroutes"], library)
            positive = np.flatnonzero(support[:, route])
            chosen = rng.choice(positive, size=min(16, len(positive)), replace=False)
            grid = design["departures_seconds"]
            queries = [(ns + int(i) // len(grid), grid[int(i) % len(grid)]) for i in chosen]
            queries += [
                (ns + int(rng.integers(meta["nda"])), int(rng.integers(300, 1441)) * 60)
                for _ in range(64 - len(queries))
            ]
            reused_count = 0
            try:
                for origin, depart in queries:
                    original, _, _ = base.query(origin, depart)
                    witness = base.witness()
                    full, _, _ = changed.query(origin, depart)
                    oracle, _, _ = changed.query(origin, depart, oracle=True)
                    survives = certificate_survives(witness, deleted)
                    reused = original if survives else full
                    assert np.all(full[ns:] >= original[ns:])
                    assert reused[ns:].tobytes() == full[ns:].tobytes()
                    assert full[ns:].tobytes() == oracle[ns:].tobytes()
                    reused_count += int(survives)

                    def hash_values(a):
                        return hashlib.sha256(np.ascontiguousarray(a[ns:]).tobytes()).hexdigest()

                    records.append(
                        {
                            "case": case,
                            "route": meta["routes"][route]["route_id"],
                            "origin": meta["points"][origin]["id"],
                            "departure_seconds": depart,
                            "certificate_survived": survives,
                            "full_sha256": hash_values(full),
                            "reused_sha256": hash_values(reused),
                            "oracle_sha256": hash_values(oracle),
                        }
                    )
            finally:
                changed.close()
            ledger.append(
                {
                    "case": case,
                    "route_id": meta["routes"][route]["route_id"],
                    "deleted_trip_occurrences": sorted(deleted),
                    "deleted_count": len(deleted),
                    "remaining_occurrences": deletion["remaining_trip_occurrences"],
                    "reduced_model_sha256": digest(target),
                    "queries": len(queries),
                    "route_dependent_hourly_queries": len(chosen),
                    "uniform_minute_queries": 64 - len(chosen),
                    "unchanged_batches_reused": reused_count,
                }
            )
            print(
                f"Frequency reduction {case + 1}/20: {meta['routes'][route]['route_id']}, "
                f"{len(deleted)} trip deletions, {reused_count}/64 unchanged",
                flush=True,
            )
    finally:
        base.close()
    with (ROOT / "results/frequency_queries.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    write_json(
        ROOT / "results/frequency_checks.json",
        {
            "seed": 20261012,
            "scenarios": len(ledger),
            "query_batches": len(records),
            "destination_arrival_comparisons": len(records) * (meta["npoints"] - ns),
            "all_byte_equal": True,
            "all_oracle_matched": True,
            "cases": ledger,
            "method": "Delete alternating weekday departures within each observed route/stop/pickup/drop-off pattern. Other dates, walking and transfer rules stay fixed.",
            "query_sampling": "Up to sixteen seeded route-dependent hourly batches; uniform City origin/minute batches fill each scenario to sixty-four. Actual counts are recorded per case. Diagnostic, not a representative frequency study.",
        },
    )
    write_json(ROOT / "results/frequency_timing.json", {"wall_seconds": time.perf_counter() - t0})


if __name__ == "__main__":
    frequency_checks()
