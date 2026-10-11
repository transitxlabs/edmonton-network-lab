"""Atlas, independent verification, exact deletion reuse and timing experiments."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from .common import INF, ROOT, space_guard, write_json
from .engine import Engine, compile_engine
from .prepare import prepare

DEPARTURES = list(range(5 * 3600, 24 * 3600 + 1, 3600))
THRESHOLDS = [1800, 2700, 3600]
SEED = 20261011


def array_hash(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def gztext(path: Path):
    raw = path.open("wb")
    compressed = gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0)
    return io.TextIOWrapper(compressed, encoding="utf-8", newline="")


class Pool:
    def __init__(self, model: Path, meta: dict[str, Any], lib: Path, workers: int = 4):
        self.local = threading.local()
        self.handles: list[Engine] = []
        self.lock = threading.Lock()
        self.model, self.meta, self.lib = model, meta, lib
        self.executor = ThreadPoolExecutor(max_workers=workers)

    def engine(self) -> Engine:
        if not hasattr(self.local, "engine"):
            self.local.engine = Engine(
                self.model, self.meta["npoints"], self.meta["nroutes"], self.lib
            )
            with self.lock:
                self.handles.append(self.local.engine)
        return self.local.engine

    def query(
        self, q: tuple[int, int], removed: int = -1, witness: bool = False, oracle: bool = False
    ):
        engine = self.engine()
        a, s, r = engine.query(*q, removed_route=removed, oracle=oracle)
        return a[self.meta["nstops"] :], s, r, engine.witness() if witness else None

    def close(self):
        self.executor.shutdown(wait=True)
        for e in self.handles:
            e.close()


def metrics(
    arrivals: np.ndarray, queries: list[tuple[int, int]], nda: int, population: np.ndarray
) -> np.ndarray:
    times = np.array([q[1] for q in queries], dtype=np.int32)
    travel = arrivals - times[:, None]
    result = np.empty((len(queries), 3, 2), dtype=np.int64)
    for j, threshold in enumerate(THRESHOLDS):
        result[:, j, 0] = np.sum((travel[:, :nda] <= threshold) * population, axis=1)
        result[:, j, 1] = np.sum(travel[:, nda:] <= threshold, axis=1)
    return result


def origin_cohorts(values: np.ndarray, population: np.ndarray, moved: np.ndarray) -> dict[str, Any]:
    """Compare origin cohorts while retaining every destination and its population."""
    result: dict[str, Any] = {
        "moved_area_count": int(moved.sum()),
        "moved_area_population": int(population[moved].sum()),
        "destination_scope": "All areas and libraries retained in both origin cohorts",
    }
    for name, mask in (
        ("all_areas", np.ones(len(population), dtype=bool)),
        ("without_moved", ~moved),
    ):
        by_time = np.average(values[mask], axis=0, weights=population[mask])
        result[name] = {
            "origin_area_count": int(mask.sum()),
            "origin_population": int(population[mask].sum()),
            "city_population_weighted_mean_access": by_time.mean(axis=0).tolist(),
            "city_population_weighted_time_range": [
                by_time.min(axis=0).tolist(),
                by_time.max(axis=0).tolist(),
            ],
        }
    return result


def batch(
    pool: Pool,
    queries: list[tuple[int, int]],
    removed: int = -1,
    base: np.ndarray | None = None,
    support: np.ndarray | None = None,
    witness_path: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    space_guard()
    t0 = time.perf_counter()
    ndest = pool.meta["npoints"] - pool.meta["nstops"]
    arrivals = base.copy() if base is not None else np.empty((len(queries), ndest), dtype=np.int32)
    footprints = np.zeros((len(queries), pool.meta["nroutes"]), dtype=np.uint8)
    ids = [i for i in range(len(queries)) if support is None or support[i, removed]]
    rounds = []
    stream = gztext(witness_path) if witness_path else None

    def task(i):
        return i, pool.query(queries[i], removed, stream is not None)

    try:
        # Keep a bounded queue, especially when recording journey certificates.
        for begin in range(0, len(ids), 128):
            for i, (a, s, r, witness) in pool.executor.map(task, ids[begin : begin + 128]):
                arrivals[i] = a
                footprints[i] = s
                rounds.append(r)
                if stream:
                    stream.write(json.dumps({"query": i, **witness}, separators=(",", ":")) + "\n")
            if begin and begin % 4096 == 0:
                space_guard()
    finally:
        if stream:
            stream.close()
    return (
        arrivals,
        footprints,
        {
            "wall_seconds": time.perf_counter() - t0,
            "recomputed_batches": len(ids),
            "total_batches": len(queries),
            "maximum_rounds": max(rounds, default=0),
        },
    )


def oracle_checks(pool: Pool, metadata: dict[str, Any], results: Path, count: int = 2000):
    rng = np.random.default_rng(SEED)
    ns, nda = metadata["nstops"], metadata["nda"]
    samples = [
        (int(rng.integers(nda)) + ns, int(rng.integers(nda)), int(rng.integers(300, 1441)) * 60)
        for _ in range(count)
    ]

    def check(sample):
        o, d, t = sample
        a, _, _, _ = pool.query((o, t))
        b, _, _, _ = pool.query((o, t), oracle=True)
        return {
            "origin": metadata["points"][o]["id"],
            "destination": metadata["points"][ns + d]["id"],
            "departure_seconds": t,
            "round_arrival_seconds": int(a[d]),
            "scan_arrival_seconds": int(b[d]),
            "matched": int(a[d]) == int(b[d]),
            "reachable": int(a[d]) < INF,
        }

    t0 = time.perf_counter()
    rows = list(pool.executor.map(check, samples))
    with (results / "oracle_queries.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    mismatches = [r for r in rows if not r["matched"]]
    write_json(
        results / "oracle.json",
        {
            "seed": SEED,
            "queries": count,
            "matches": count - len(mismatches),
            "match_rate": (count - len(mismatches)) / count,
            "reachable_queries": sum(r["reachable"] for r in rows),
            "disagreements": mismatches,
            "departure_distribution": "uniform integer minute from 05:00 through 24:00 inclusive",
            "origin_destination_distribution": "independent uniform DA draws; replacement",
        },
    )
    write_json(results / "oracle_timing.json", {"wall_seconds": time.perf_counter() - t0})
    if mismatches:
        raise RuntimeError(
            "Independent oracle disagreements: investigate before any result release"
        )


def timetable_components(
    walk: np.ndarray, geometry: np.ndarray, scheduled: np.ndarray
) -> np.ndarray:
    """Signed accounting independent of any service-span extension."""
    if np.any(walk > geometry) or np.any(scheduled > geometry):
        raise RuntimeError("Geometry reference does not dominate walking and schedule")
    return np.stack([walk, geometry - walk, scheduled - geometry], axis=-1)


def decompose(
    root: Path, pool: Pool, meta: dict[str, Any], queries, base_metrics, population, library: Path
):
    ns, nda = meta["nstops"], meta["nda"]
    print("Constructing walking, geometry and timetable decomposition", flush=True)

    def references(o):
        engine = pool.engine()
        geometry = engine.geometry(o)[ns:]
        # With all services deleted, round routing is exactly the walking baseline.
        # Obtain it directly from the frozen walking prefix to avoid a service assumption.
        return geometry

    geometry_arrivals = np.stack(list(pool.executor.map(references, range(ns, ns + nda))))
    import struct

    walks = []
    with (root / "build/model.bin").open("rb") as f:
        f.read(20)
        for _ in range(meta["npoints"]):
            n = struct.unpack("<i", f.read(4))[0]
            walks.append(np.frombuffer(f.read(n * 8), dtype="<i4").reshape(-1, 2))
    walking_arrivals = np.full((nda, meta["npoints"] - ns), INF, dtype=np.int32)
    for i, o in enumerate(range(ns, ns + nda)):
        walking_arrivals[i, i] = 0
        for target, cost in walks[o]:
            if target >= ns:
                walking_arrivals[i, target - ns] = cost
    zero_queries = [(o, 0) for o in range(ns, ns + nda)]
    geom = metrics(geometry_arrivals, zero_queries, nda, population)
    walk = metrics(walking_arrivals, zero_queries, nda, population)
    geom = np.repeat(geom, len(DEPARTURES), axis=0)
    walk = np.repeat(walk, len(DEPARTURES), axis=0)
    values = timetable_components(walk, geom, base_metrics)
    if not np.array_equal(values.sum(axis=-1), base_metrics):
        raise RuntimeError("Decomposition fails exact additive accounting")
    np.savez_compressed(root / "results/decomposition.npz", values=values)
    write_json(
        root / "results/decomposition.json",
        {
            "components": ["walking", "geometry", "timetable"],
            "order": "walking; zero-wait shifted-trip geometry; original schedule",
            "identity": "walking + geometry + timetable = sampled scheduled access",
            "limits": "Signed counterfactual accounting, not causal attribution. Timetable combines headway and span because the extension rule creates artificial all-day service for short patterns. No extension is used.",
        },
    )


def run(root: Path = ROOT, replay: bool = False, skip_prepare: bool = False):
    space_guard()
    results = root / "results"
    results.mkdir(exist_ok=True)
    (results / "arrays").mkdir(exist_ok=True)
    meta = (
        json.loads((root / "data/manifests/model.json").read_text())
        if skip_prepare
        else prepare(root)
    )
    ns, nda, nr = meta["nstops"], meta["nda"], meta["nroutes"]
    population = np.array([p["population"] for p in meta["points"][ns : ns + nda]], dtype=np.int64)
    queries = [(o, t) for o in range(ns, ns + nda) for t in DEPARTURES]
    write_json(
        results / "design.json",
        {
            "seed": SEED,
            "departures_seconds": DEPARTURES,
            "thresholds_seconds": THRESHOLDS,
            "service_date": meta["service_date"],
            "origins": nda,
            "origin_departure_batches": len(queries),
            "origin_population": int(population.sum()),
            "destinations": meta["npoints"] - ns,
            "route_deletions": nr,
            "workers": 4,
            "subset_reason": "Pilot benchmark: 100 origin queries at 08:00 took 0.4609 seconds on one worker. A subsequent four-worker pilot took about 4.5 seconds per route for six departures. The full minute-grid deletion check projects about 58 hours, beyond the report deadline. Hourly departures retain every origin and every route within the compute window.",
            "profile_limit": "Twenty hourly departures across the day; no between-sample interpolation or full-minute profile claim.",
            "intervals": "Ranges over the sampled departures and DA quantiles, not sampling confidence intervals.",
        },
    )
    lib = compile_engine(root / "build")
    pool = Pool(root / "build/model.bin", meta, lib)
    try:
        oracle_checks(pool, meta, results)
        print("Independent oracle checks passed", flush=True)
        base, support, base_timing = batch(
            pool, queries, witness_path=results / "optimal_witnesses.jsonl.gz"
        )
        np.save(results / "arrays/base_arrivals.npy", base)
        np.save(results / "arrays/route_support.npy", support)
        base_metrics = metrics(base, queries, nda, population)
        np.savez_compressed(results / "access_profiles.npz", values=base_metrics)
        print(f"Base atlas: {len(queries)} batches, {base_timing['wall_seconds']:.1f}s", flush=True)
        rows = []
        for i, (o, t) in enumerate(queries):
            row = {
                "origin": meta["points"][o]["id"],
                "departure_seconds": t,
                "origin_population": int(population[(o - ns)]),
            }
            for j, threshold in enumerate(THRESHOLDS):
                row[f"population_{threshold // 60}"] = int(base_metrics[i, j, 0])
                row[f"libraries_{threshold // 60}"] = int(base_metrics[i, j, 1])
            rows.append(row)
        with (results / "access_profiles.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        timings = []
        deltas = np.empty((nr, len(queries), 3, 2), dtype=np.int64)
        rng = np.random.default_rng(SEED)
        order = rng.permutation(nr).tolist()
        full_ids = set(order[:20]) if replay else set(order)
        for k, r in enumerate(order):
            reused, _, reuse_timing = batch(pool, queries, r, base, support)
            if np.any(reused < base):
                raise RuntimeError("A route deletion improved an arrival: invalid result")
            reuse_hash = array_hash(reused)
            full_timing = None
            full_hash = None
            if r in full_ids:
                full, _, full_timing = batch(pool, queries, r)
                full_hash = array_hash(full)
                if full.tobytes() != reused.tobytes():
                    mismatch = np.argwhere(full != reused)[0].tolist()
                    write_json(
                        results / "deletion_failure.json", {"route": r, "mismatch": mismatch}
                    )
                    raise RuntimeError("Reuse differs from full recomputation")
            changed_metrics = metrics(reused, queries, nda, population)
            deltas[r] = base_metrics - changed_metrics
            if np.any(deltas[r] < 0):
                raise RuntimeError("A route deletion increased access")
            timings.append(
                {
                    "route_index": r,
                    "route_id": meta["routes"][r]["route_id"],
                    "reuse": reuse_timing,
                    "full": full_timing,
                    "reuse_sha256": reuse_hash,
                    "full_sha256": full_hash,
                    "byte_equal": full_hash == reuse_hash if full_hash else None,
                    "speedup": full_timing["wall_seconds"] / reuse_timing["wall_seconds"]
                    if full_timing
                    else None,
                }
            )
            write_json(results / "deletion_timings.json", timings)
            if k % 5 == 0 or k == nr - 1:
                print(
                    f"N-1 {k + 1}/{nr}: {meta['routes'][r]['route_id']}, affected {reuse_timing['recomputed_batches']}/{len(queries)}, reused {reuse_timing['wall_seconds']:.1f}s, full {full_timing['wall_seconds'] if full_timing else 0:.1f}s",
                    flush=True,
                )
        np.savez_compressed(results / "n1_profiles.npz", values=deltas)
        weights = np.repeat(population, len(DEPARTURES))
        # Per-departure ranks use the same population weights and identifier tie breaker.
        hourly_loss = np.average(
            deltas.reshape(nr, nda, len(DEPARTURES), 3, 2)[:, :, :, 1, 0],
            axis=1,
            weights=population,
        )
        hourly_ranks = np.empty((nr, len(DEPARTURES)), dtype=np.int32)
        for departure in range(len(DEPARTURES)):
            order_by_loss = sorted(
                range(nr),
                key=lambda r: (-hourly_loss[r, departure], meta["routes"][r]["route_id"]),
            )
            for rank, r in enumerate(order_by_loss, 1):
                hourly_ranks[r, departure] = rank
        ranking = []
        for r in range(nr):
            row = {
                "route_id": meta["routes"][r]["route_id"],
                "route_name": meta["routes"][r]["route_long_name"],
                "rank_45_min": int(hourly_ranks[r].min()),
                "rank_45_max": int(hourly_ranks[r].max()),
                "top_ten_departures_45": int(np.count_nonzero(hourly_ranks[r] <= 10)),
            }
            for j, threshold in enumerate(THRESHOLDS):
                row[f"population_weighted_loss_{threshold // 60}"] = float(
                    np.average(deltas[r, :, j, 0], weights=weights)
                )
                row[f"population_weighted_library_loss_{threshold // 60}"] = float(
                    np.average(deltas[r, :, j, 1], weights=weights)
                )
            ranking.append(row)
        ranking.sort(key=lambda r: (-r["population_weighted_loss_45"], r["route_id"]))
        with (results / "n1_ranking.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["rank"] + list(ranking[0]))
            writer.writeheader()
            writer.writerows({"rank": i + 1, **r} for i, r in enumerate(ranking))
        with gztext(results / "n1_area_summary.csv.gz") as f:
            area_writer = csv.writer(f)
            area_writer.writerow(
                [
                    "route",
                    "origin",
                    "population_loss_30",
                    "population_loss_45",
                    "population_loss_60",
                    "library_loss_30",
                    "library_loss_45",
                    "library_loss_60",
                ]
            )
            means = deltas.reshape(nr, nda, len(DEPARTURES), 3, 2).mean(axis=2)
            for r in range(nr):
                for i in range(nda):
                    area_writer.writerow(
                        [
                            meta["routes"][r]["route_id"],
                            meta["points"][ns + i]["id"],
                            *means[r, i, :, 0],
                            *means[r, i, :, 1],
                        ]
                    )
        any_effect = np.any(deltas > 0, axis=(1, 2, 3))
        mean_scores = np.average(deltas[..., 0], axis=1, weights=weights)
        primary_30_45 = np.any(mean_scores[:, :2] > 0, axis=1)
        primary_45_60 = np.any(mean_scores[:, 1:] > 0, axis=1)
        write_json(
            results / "ranking_sensitivity.json",
            {
                "primary_routes": int(primary_30_45.sum()),
                "primary_routes_45_60": int(primary_45_60.sum()),
                "primary_set": "Non-zero population loss on either side of each budget comparison",
                "rho_30_45": float(
                    spearmanr(
                        mean_scores[primary_30_45, 0], mean_scores[primary_30_45, 1]
                    ).statistic
                ),
                "rho_45_60": float(
                    spearmanr(
                        mean_scores[primary_45_60, 1], mean_scores[primary_45_60, 2]
                    ).statistic
                ),
                "top_five": {
                    str(budget): sorted(
                        ranking,
                        key=lambda r: (-r[f"population_weighted_loss_{budget}"], r["route_id"]),
                    )[:5]
                    for budget in (30, 45, 60)
                },
                "hourly_rank_ties": "Route identifier breaks equal-score ties",
                "departures": len(DEPARTURES),
            },
        )
        np.savez_compressed(
            results / "route_hourly_ranks.npz", ranks=hourly_ranks, scores=hourly_loss
        )
        decompose(root, pool, meta, queries, base_metrics, population, lib)
        city_access = np.average(base_metrics, axis=0, weights=weights)
        by_time = np.average(
            base_metrics.reshape(nda, len(DEPARTURES), 3, 2), axis=0, weights=population
        )
        matched = sum(t["byte_equal"] is True for t in timings)
        full_seconds = sum(t["full"]["wall_seconds"] for t in timings if t["full"])
        reuse_seconds = sum(t["reuse"]["wall_seconds"] for t in timings)
        write_json(
            results / "summary.json",
            {
                "service_date": meta["service_date"],
                "routes": nr,
                "stops": ns,
                "published_trips": 86628,
                "active_trip_occurrences": meta["trip_occurrences"],
                "dissemination_areas": nda,
                "population": int(population.sum()),
                "library_destinations": meta["npoints"] - ns - nda,
                "city_population_weighted_mean_access": city_access.tolist(),
                "origin_cohorts": origin_cohorts(
                    base_metrics.reshape(nda, len(DEPARTURES), 3, 2),
                    population,
                    np.array([p["access_point"]["moved"] for p in meta["points"][ns : ns + nda]]),
                ),
                "city_population_weighted_time_range": [
                    by_time.min(axis=0).tolist(),
                    by_time.max(axis=0).tolist(),
                ],
                "base_arrival_sha256": array_hash(base),
                "base_support_sha256": array_hash(support),
                "n1_delta_sha256": array_hash(deltas),
                "route_order_seed": SEED,
                "full_recomputation_checks": matched,
                "route_deletions": nr,
                "top_routes": ranking[:10],
                "sampled_departures_seconds": DEPARTURES,
            },
        )
        benchmark = {
            "base": base_timing,
            "full_seconds": full_seconds,
            "reuse_seconds": reuse_seconds,
            "full_routes_timed": len(full_ids),
            "aggregate_speedup": full_seconds / reuse_seconds if not replay else None,
            "timing_scope": "Four workers, loaded model; includes allocation and result copying; excludes preparation and metric aggregation.",
        }
        if not replay:
            affected_timings = [t for t in timings if any_effect[t["route_index"]]]
            benchmark["any_effect_routes"] = len(affected_timings)
            benchmark["any_effect_full_seconds"] = sum(
                t["full"]["wall_seconds"] for t in affected_timings
            )
            benchmark["any_effect_reuse_seconds"] = sum(
                t["reuse"]["wall_seconds"] for t in affected_timings
            )
            benchmark["any_effect_speedup"] = (
                benchmark["any_effect_full_seconds"] / benchmark["any_effect_reuse_seconds"]
            )
            by_route = {t["route_id"]: t for t in timings}
            benchmark["top_five_speedups"] = [
                {"route_id": r["route_id"], "speedup": by_route[r["route_id"]]["speedup"]}
                for r in ranking[:5]
            ]
            # Documents and clean replays retain the latest complete benchmark.
            write_json(results / "reference_benchmark.json", benchmark)
        write_json(results / "benchmark.json", benchmark)
    finally:
        pool.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--skip-prepare", action="store_true")
    args = parser.parse_args()
    run(replay=args.replay, skip_prepare=args.skip_prepare)


if __name__ == "__main__":
    main()
