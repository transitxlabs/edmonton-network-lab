"""Access counts, exact deletion reuse, the oracle check and the what-if query.

The fixture network has stops A, B and C, two dissemination areas and one library.
From area D0 at 08:00, route R0 reaches area D1 in 1,120 s, route R1 reaches the
library in 2,530 s, and route R2 reaches D1 only after the sixty-minute horizon.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys

import numpy as np
import pytest

from network_lab import experiment, query
from network_lab.common import INF
from network_lab.engine import Engine, compile_engine, delete_service, write_model

T = 8 * 3600
NSTOPS, NDA = 3, 2
D0, D1, LIBRARY = 3, 4, 5
POPULATION = np.array([100, 50], dtype=np.int64)


def edges(*pairs):
    return np.array(pairs, dtype=np.int32).reshape(-1, 2)


WALKS = [
    edges((0, 0), (3, 60)),
    edges((1, 0), (4, 120)),
    edges((2, 0), (5, 30)),
    edges((3, 0), (0, 60)),
    edges((4, 0), (1, 120)),
    edges((5, 0), (2, 30)),
]
BOARDS = [edges((0, 0)), edges((1, 0)), edges((2, 0))]
TRIPS = [
    {"route": 0, "rows": [[0, T + 100, T + 100, 0, 0], [1, T + 1000, T + 1000, 0, 0]]},
    {"route": 1, "rows": [[0, T + 200, T + 200, 0, 0], [2, T + 2500, T + 2500, 0, 0]]},
    {"route": 2, "rows": [[0, T + 300, T + 300, 0, 0], [1, T + 4000, T + 4000, 0, 0]]},
]
META = {
    "service_date": "2026-10-13",
    "nstops": NSTOPS,
    "nda": NDA,
    "npoints": 6,
    "nroutes": 3,
    "routes": [{"route_id": r} for r in ("R0", "R1", "R2")],
    "points": [
        {"id": "A", "kind": "stop"},
        {"id": "B", "kind": "stop"},
        {"id": "C", "kind": "stop"},
        {"id": "D0", "kind": "dissemination_area", "population": 100},
        {"id": "D1", "kind": "dissemination_area", "population": 50},
        {"id": "library:1", "kind": "library"},
    ],
}


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    return compile_engine(tmp_path_factory.mktemp("native"))


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "model.bin"
    write_model(path, NSTOPS, 6, 3, WALKS, BOARDS, TRIPS)
    return path


@pytest.fixture
def pool(model, library, monkeypatch):
    monkeypatch.setattr(experiment, "space_guard", lambda: None)
    p = experiment.Pool(model, META, library, workers=2)
    yield p
    p.close()


def test_metrics_count_people_and_libraries_within_each_budget():
    depart = 1000
    queries = [(D0, depart)]
    # Two areas then two libraries; INF marks an unreachable destination.
    arrivals = np.array([[depart + 1800, depart + 2701, depart + 2700, INF]], dtype=np.int32)
    values = experiment.metrics(arrivals, queries, 2, POPULATION)
    assert values.shape == (1, 3, 2)
    # Budgets are inclusive: 1,800 s counts at 30 minutes, 2,701 s only at 60 minutes.
    assert values[0].tolist() == [[100, 0], [100, 1], [150, 1]]


def test_metrics_use_each_query_departure_time():
    queries = [(D0, 0), (D0, 3600)]
    arrivals = np.array([[1700, 0], [3600 + 3601, 3600]], dtype=np.int32)
    values = experiment.metrics(arrivals, queries, 1, POPULATION[:1])
    assert values[:, :, 0].tolist() == [[100, 100, 100], [0, 0, 0]]
    assert values[:, :, 1].tolist() == [[1, 1, 1], [1, 1, 1]]


def test_base_access_from_the_fixture_network(pool):
    queries = [(D0, T), (D1, T)]
    base, support, timing = experiment.batch(pool, queries)
    assert timing["recomputed_batches"] == timing["total_batches"] == 2
    # Arrivals at D0, D1 and the library.
    assert base[0].tolist() == [T, T + 1120, T + 2530]
    assert base[1].tolist() == [INF, T, INF]
    # The selected journeys from D0 use R0 and R1; R2 is never needed.
    assert support.tolist() == [[1, 1, 0], [0, 0, 0]]
    values = experiment.metrics(base, queries, NDA, POPULATION)
    assert values[0].tolist() == [[150, 0], [150, 1], [150, 1]]
    assert values[1].tolist() == [[50, 0], [50, 0], [50, 0]]


@pytest.mark.parametrize(
    ("removed", "recomputed", "expected_d0"),
    [
        (0, 1, [T, INF, T + 2530]),
        (1, 1, [T, T + 1120, INF]),
        (2, 0, [T, T + 1120, T + 2530]),
    ],
)
def test_deletion_reuse_matches_full_rerun(pool, removed, recomputed, expected_d0):
    queries = [(D0, T), (D1, T)]
    base, support, _ = experiment.batch(pool, queries)
    reused, _, reuse_timing = experiment.batch(pool, queries, removed, base, support)
    full, _, full_timing = experiment.batch(pool, queries, removed)
    # Only batches whose selected journeys use the removed route are rerouted.
    assert reuse_timing["recomputed_batches"] == recomputed
    assert full_timing["recomputed_batches"] == 2
    assert reused.tobytes() == full.tobytes()
    assert reused[0].tolist() == expected_d0
    assert np.all(reused >= base)
    loss = experiment.metrics(base, queries, NDA, POPULATION) - experiment.metrics(
        reused, queries, NDA, POPULATION
    )
    assert np.all(loss >= 0)


def test_route_deletion_file_matches_query_time_route_removal(model, library, tmp_path):
    reduced = tmp_path / "without_r0.bin"
    receipt = delete_service(model, reduced, set(), {0})
    assert receipt == {
        "original_trip_occurrences": 3,
        "remaining_trip_occurrences": 2,
        "new_to_base_trip_indices": [1, 2],
    }
    base, changed = Engine(model, 6, 3, library), Engine(reduced, 6, 3, library)
    try:
        for origin in range(6):
            for oracle in (False, True):
                expected, _, _ = base.query(origin, T, removed_route=0, oracle=oracle)
                actual, _, _ = changed.query(origin, T, oracle=oracle)
                np.testing.assert_array_equal(actual, expected)
    finally:
        base.close()
        changed.close()
    with pytest.raises(ValueError, match="outside the frozen model"):
        delete_service(model, tmp_path / "bad.bin", {3})


def test_oracle_check_records_matches_and_blocks_disagreements(library, tmp_path, monkeypatch):
    # A day of service so random 05:00 to 24:00 departures can board.
    trips = []
    for start in range(18000, 90000, 900):
        for route, stop, board, ride in ((0, 1, start, 600), (1, 2, start + 60, 900)):
            rows = [[0, board, board, 0, 0], [stop, board + ride, board + ride, 0, 0]]
            trips.append({"route": route, "rows": rows})
    path = tmp_path / "day.bin"
    write_model(path, NSTOPS, 6, 3, WALKS, BOARDS, trips)
    monkeypatch.setattr(experiment, "space_guard", lambda: None)
    pool = experiment.Pool(path, META, library, workers=2)
    try:
        experiment.oracle_checks(pool, META, tmp_path, count=60)
        oracle = json.loads((tmp_path / "oracle.json").read_text())
        assert oracle["queries"] == oracle["matches"] == 60
        assert oracle["match_rate"] == 1.0
        assert oracle["disagreements"] == []
        assert 0 < oracle["reachable_queries"] <= 60
        with (tmp_path / "oracle_queries.csv").open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 60
        assert all(18000 <= int(r["departure_seconds"]) <= 86400 for r in rows)
        assert {r["origin"] for r in rows} <= {"D0", "D1"}

        original = pool.query

        def wrong_oracle(q, removed=-1, witness=False, oracle=False):
            a, s, r, w = original(q, removed, witness, oracle)
            return (a + 1 if oracle else a), s, r, w

        monkeypatch.setattr(pool, "query", wrong_oracle)
        with pytest.raises(RuntimeError, match="Independent oracle disagreements"):
            experiment.oracle_checks(pool, META, tmp_path, count=5)
        assert json.loads((tmp_path / "oracle.json").read_text())["matches"] == 0
    finally:
        pool.close()


@pytest.fixture
def query_root(tmp_path, model, library, monkeypatch):
    (tmp_path / "build").mkdir(exist_ok=True)
    shutil.copy(model, tmp_path / "build/model.bin")
    shutil.copy(library, tmp_path / "build/libnetwork.dylib")
    write_meta = tmp_path / "data/manifests/model.json"
    write_meta.parent.mkdir(parents=True)
    write_meta.write_text(json.dumps(META))
    monkeypatch.setattr(query, "ROOT", tmp_path)
    monkeypatch.setattr(query, "space_guard", lambda: None)
    return tmp_path


def run_query(monkeypatch, capsys, *arguments):
    monkeypatch.setattr(sys, "argv", ["network_lab.query", *arguments])
    query.main()
    return json.loads(capsys.readouterr().out)


def test_what_if_query_reports_population_and_library_loss(query_root, monkeypatch, capsys):
    answer = run_query(
        monkeypatch, capsys, "--origin", "D0", "--departure", "08:00", "--remove-route", "R0"
    )
    assert answer["departure_seconds"] == T
    assert answer["removed_routes"] == ["R0"]
    assert answer["surviving_certificate_reused"] is False
    assert [a["threshold_minutes"] for a in answer["access"]] == [30, 45, 60]
    for budget in answer["access"]:
        assert budget["base_population"] == 150
        assert budget["changed_population"] == 100
        assert budget["population_lost"] == 50
    assert [a["base_libraries"] for a in answer["access"]] == [0, 1, 1]
    assert [a["changed_libraries"] for a in answer["access"]] == [0, 1, 1]
    assert list((query_root / "build/scenarios").glob("*.bin"))


def test_what_if_query_reuses_certificate_for_unused_route(query_root, monkeypatch, capsys):
    answer = run_query(
        monkeypatch, capsys, "--origin", "D0", "--departure", "08:00", "--remove-route", "R2"
    )
    assert answer["surviving_certificate_reused"] is True
    assert all(a["population_lost"] == 0 for a in answer["access"])
    assert not (query_root / "build/scenarios").exists()


def test_what_if_query_combines_route_deletions(query_root, monkeypatch, capsys):
    answer = run_query(
        monkeypatch,
        capsys,
        "--origin",
        "D0",
        "--departure",
        "08:00",
        "--remove-route",
        "R1",
        "--remove-route",
        "R0",
    )
    assert answer["removed_routes"] == ["R0", "R1"]
    assert [a["changed_population"] for a in answer["access"]] == [100, 100, 100]
    assert [a["changed_libraries"] for a in answer["access"]] == [0, 0, 0]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--origin", "D0", "--departure", "04:59"],
        ["--origin", "D0", "--departure", "24:01"],
        ["--origin", "D0", "--departure", "08:60"],
        ["--origin", "D0", "--departure", "0800"],
        ["--origin", "A", "--departure", "08:00"],
        ["--origin", "D0", "--departure", "08:00", "--remove-route", "R9"],
    ],
)
def test_what_if_query_rejects_invalid_requests(query_root, monkeypatch, capsys, arguments):
    monkeypatch.setattr(sys, "argv", ["network_lab.query", *arguments])
    with pytest.raises(SystemExit) as stopped:
        query.main()
    assert stopped.value.code == 2
    assert capsys.readouterr().out == ""
