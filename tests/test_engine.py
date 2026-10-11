"""Small adversarial schedules and an independently enumerated journey oracle."""

from __future__ import annotations

import heapq
import random
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from network_lab.common import INF
from network_lab.engine import (
    Engine,
    certificate_survives,
    compile_engine,
    delete_service,
    write_model,
)
from network_lab.gtfs import occurrences, seconds


@pytest.fixture(scope="session")
def library(tmp_path_factory):
    return compile_engine(tmp_path_factory.mktemp("native"))


def make_engine(tmp: Path, lib: Path, trips, walks, boards=None, nroutes=3):
    n = len(walks)
    boards = boards or [np.array([(i, 0)], dtype=np.int32) for i in range(n - 1)]
    path = tmp / "fixture.bin"
    write_model(path, n - 1, n, nroutes, walks, boards, trips)
    return Engine(path, n, nroutes, lib)


def brute(trips, walks, boards, origin, depart, removed=-1):
    """Enumerate every permitted board/alight pair, with earliest-ready Dijkstra."""
    n = len(walks)
    best = [INF] * (n - 1)
    result = [INF] * n
    result[origin] = depart
    queue = []
    for stop, cost in walks[origin]:
        result[stop] = min(result[stop], depart + cost)
        if stop < n - 1:
            best[stop] = min(best[stop], depart + cost)
            heapq.heappush(queue, (depart + cost, int(stop)))
    while queue:
        now, stop = heapq.heappop(queue)
        if now != best[stop] or now > depart + 3600:
            continue
        for trip in trips:
            if trip["route"] == removed:
                continue
            for k, row in enumerate(trip["rows"]):
                if row[0] != stop or row[3] or row[2] < now:
                    continue
                for rr in trip["rows"][k + 1 :]:
                    if rr[4] or rr[1] > depart + 3600:
                        continue
                    for d, cost in walks[rr[0]]:
                        if rr[1] + cost <= depart + 3600:
                            result[d] = min(result[d], rr[1] + cost)
                    for d, cost in boards[rr[0]]:
                        a = rr[1] + cost
                        if a <= depart + 3600 and a < best[d]:
                            best[d] = a
                            heapq.heappush(queue, (a, int(d)))
    return np.array(result, dtype=np.int32)


def test_time_parsing():
    assert seconds("25:01:03") == 90063
    for value in ["12:60:00", "10:01:60", "", "12:1:00", "-1:00:00"]:
        with pytest.raises(ValueError):
            seconds(value)


def test_adjacent_service_dates_and_long_trip_guard():
    feed = {
        "days": {"2026-10-12": {"weekday"}},
        "times": {"night": [[0, 90000, 90000, 0, 0], [1, 104400, 104400, 0, 0]]},
        "trips": {"night": {"service_id": "weekday", "route_id": "a"}},
        "route_index": {"a": 0},
    }
    trips, ids = occurrences(feed, date(2026, 10, 13))
    assert ids == ["2026-10-12:night"]
    assert trips[0]["rows"][-1][1] == 18000
    feed["times"]["night"][-1][1:3] = [190800, 190800]
    with pytest.raises(ValueError, match="adjacent-date"):
        occurrences(feed, date(2026, 10, 13))


def test_overtaking_pickup_dropoff_and_transfer_rules(tmp_path, library):
    walks = [np.array([(i, 0)], dtype=np.int32) for i in range(5)]
    walks[0] = np.array([(0, 0), (4, 1200)], dtype=np.int32)
    walks[3] = np.array([(3, 0), (4, 10)], dtype=np.int32)
    walks[4] = np.array([(4, 0), (0, 0)], dtype=np.int32)
    boards = [np.array([(i, 0)], dtype=np.int32) for i in range(4)]
    boards[1] = np.array([(1, 100)], dtype=np.int32)
    trips = [
        {"route": 0, "rows": [[0, 100, 100, 0, 0], [1, 500, 500, 0, 0], [3, 700, 700, 0, 0]]},
        {"route": 1, "rows": [[0, 200, 200, 0, 0], [1, 300, 300, 0, 0]]},
        {"route": 2, "rows": [[1, 350, 350, 0, 0], [3, 400, 400, 0, 0]]},
        {"route": 2, "rows": [[1, 450, 450, 0, 0], [3, 550, 550, 0, 0]]},
        {"route": 0, "rows": [[0, 50, 50, 1, 0], [3, 100, 100, 0, 0]]},
        {"route": 0, "rows": [[0, 60, 60, 0, 0], [3, 90, 90, 0, 1]]},
    ]
    e = make_engine(tmp_path, library, trips, walks, boards)
    for removed in [-1, 0, 1, 2]:
        a, _, _ = e.query(0, 0, removed_route=removed)
        b, _, _ = e.query(0, 0, removed_route=removed, oracle=True)
        expected = brute(trips, walks, boards, 0, 0, removed)
        np.testing.assert_array_equal(a, expected)
        np.testing.assert_array_equal(b, expected)
    assert e.query(0, 0)[0][4] == 560
    e.close()


def test_zero_time_connections_do_not_run_backwards(tmp_path, library):
    walks = [np.array([(i, 0)], dtype=np.int32) for i in range(4)]
    walks[0] = np.array([(0, 0), (3, 0)], dtype=np.int32)
    trips = [{"route": 0, "rows": [[0, 100, 100, 0, 0], [1, 100, 100, 0, 0], [2, 100, 100, 0, 0]]}]
    e = make_engine(tmp_path, library, trips, walks)
    for o in [0, 1, 2, 3]:
        for oracle in [False, True]:
            a, _, _ = e.query(o, 0, oracle=oracle)
            expected = brute(trips, walks, [np.array([(i, 0)]) for i in range(3)], o, 0)
            np.testing.assert_array_equal(a, expected)
    assert e.query(2, 0, oracle=True)[0][0] == INF
    e.close()


def test_random_schedules_against_enumeration(tmp_path, library):
    seed = random.Random(20261011)
    for _ in range(80):
        walks = [np.array([(i, 0)], dtype=np.int32) for i in range(7)]
        for i in range(7):
            walks[i] = np.array(
                [
                    (j, 0 if j == i else seed.randrange(0, 120))
                    for j in range(7)
                    if j == i or seed.random() < 0.15
                ],
                dtype=np.int32,
            )
        boards = [x[x[:, 0] < 6].copy() for x in walks[:6]]
        for a in boards:
            a[:, 1] += seed.choice([0, 0, 15])
        trips = []
        for _ in range(15):
            t = seed.randrange(0, 1200)
            rr = []
            for _ in range(seed.randrange(2, 7)):
                arr = t + seed.choice([0, 0, 30, 70])
                t = arr + seed.choice([0, 0, 10])
                rr.append(
                    [seed.randrange(6), arr, t, int(seed.random() < 0.2), int(seed.random() < 0.2)]
                )
            trips.append({"route": seed.randrange(3), "rows": rr})
        e = make_engine(tmp_path, library, trips, walks, boards)
        for _ in range(10):
            o, t, removed = seed.randrange(7), seed.randrange(0, 1200), seed.choice([-1, 0, 1, 2])
            expected = brute(trips, walks, boards, o, t, removed)
            a, _, _ = e.query(o, t, removed_route=removed)
            b, _, _ = e.query(o, t, removed_route=removed, oracle=True)
            np.testing.assert_array_equal(a, expected)
            np.testing.assert_array_equal(b, expected)
        e.close()


def test_selected_witness_reuse_with_tied_routes(tmp_path, library):
    walks = [np.array([(i, 0)], dtype=np.int32) for i in range(3)]
    walks[1] = np.array([(1, 0), (2, 0)], dtype=np.int32)
    walks[2] = np.array([(2, 0), (0, 0)], dtype=np.int32)
    trips = [{"route": r, "rows": [[0, 100, 100, 0, 0], [1, 200, 200, 0, 0]]} for r in (0, 1)]
    e = make_engine(tmp_path, library, trips, walks)
    base, support, _ = e.query(0, 0)
    assert support.tolist() == [1, 0, 0]
    witness = e.witness()
    assert witness["destination_leg"][0] >= 0
    assert base[2] == e.query(0, 0, removed_route=1)[0][2]
    assert base[2] == e.query(0, 0, removed_route=0)[0][2]
    assert base[2] == e.query(0, 0, removed_trip=0)[0][2]
    assert base[2] == e.query(0, 0, removed_trip=1)[0][2]
    e.close()


def test_no_fixed_transfer_limit_and_midnight(tmp_path, library):
    walks = [np.array([(i, 0)], dtype=np.int32) for i in range(13)]
    walks[11] = np.array([(11, 0), (12, 0)], dtype=np.int32)
    trips = []
    for i in range(11):
        t = 86400 + i * 100
        trips.append({"route": i % 3, "rows": [[i, t, t, 0, 0], [i + 1, t + 90, t + 90, 0, 0]]})
    e = make_engine(tmp_path, library, trips, walks)
    a, _, rounds = e.query(0, 86400)
    b, _, _ = e.query(0, 86400, oracle=True)
    assert rounds > 6
    assert a[12] == 87490
    np.testing.assert_array_equal(a, b)
    witness = e.witness()
    path = witness["destination_leg"][0]
    journey = []
    while path >= 0:
        leg = witness["legs"][path]
        journey.append(leg[1])
        path = leg[0]
    assert len(journey) == 11
    assert e.query(0, 86400, removed_trip=5)[0][12] == INF
    e.close()


def test_geometry_reference_dominates_schedule(tmp_path, library):
    walks = [np.array([(i, 0)], dtype=np.int32) for i in range(4)]
    walks[2] = np.array([(2, 0), (3, 20)], dtype=np.int32)
    trips = [
        {"route": 0, "rows": [[0, 200, 200, 0, 0], [1, 300, 300, 0, 0]]},
        {"route": 1, "rows": [[1, 500, 500, 0, 0], [2, 550, 550, 0, 0]]},
    ]
    e = make_engine(tmp_path, library, trips, walks)
    assert e.geometry(0)[3] == 170
    assert e.query(0, 0)[0][3] == 570
    e.close()


def test_frequency_reduction_by_actual_trip_deletion(tmp_path, library):
    walks = [np.array([(i, 0)], dtype=np.int32) for i in range(3)]
    walks[1] = np.array([(1, 0), (2, 20)], dtype=np.int32)
    trips = [
        {"route": 0, "rows": [[0, t, t, 0, 0], [1, t + 100, t + 100, 0, 0]]}
        for t in [100, 200, 300, 400]
    ]
    base = make_engine(tmp_path, library, trips, walks)
    reduced = tmp_path / "reduced.bin"
    receipt = delete_service(tmp_path / "fixture.bin", reduced, {0, 2})
    assert receipt["remaining_trip_occurrences"] == 2
    new = Engine(reduced, 3, 3, library)
    for depart in [0, 150, 250, 350, 450]:
        original, _, _ = base.query(0, depart)
        witness = base.witness()
        changed, _, _ = new.query(0, depart)
        oracle, _, _ = new.query(0, depart, oracle=True)
        np.testing.assert_array_equal(changed, oracle)
        assert np.all(changed >= original)
        if certificate_survives(witness, {0, 2}):
            np.testing.assert_array_equal(original, changed)
    base.close()
    new.close()


def test_original_to_moved_walk_changes_boarding_and_all_routing_modes(tmp_path, library):
    # Original origin 3 takes 240 seconds to its access point, then 10 to stop 0.
    # Omitting that walk would catch the first trip and report arrival 120.
    walks = [np.array([(i, 0)], dtype=np.int32) for i in range(4)]
    walks[3] = np.array([(3, 0), (0, 250), (2, 1000)], dtype=np.int32)
    walks[1] = np.array([(1, 0), (2, 20)], dtype=np.int32)
    trips = [
        {"route": 0, "rows": [[0, t, t, 0, 0], [1, t + 100, t + 100, 0, 0]]} for t in (20, 300)
    ]
    e = make_engine(tmp_path, library, trips, walks)
    try:
        assert e.geometry(3)[2] == 370
        for oracle in (False, True):
            assert e.query(3, 0, oracle=oracle)[0][2] == 420
            assert e.query(3, 0, removed_route=0, oracle=oracle)[0][2] == 1000
            assert e.query(3, 0, removed_trip=1, oracle=oracle)[0][2] == 1000
    finally:
        e.close()
