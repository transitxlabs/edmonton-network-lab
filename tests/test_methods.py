"""Regression checks for walking connectivity and timetable accounting."""

import json

import numpy as np
import pytest
from shapely.geometry import LineString, box, mapping

from network_lab.common import digest, require_walking_validation, write_json
from network_lab.experiment import origin_cohorts, timetable_components
from network_lab.prepare import check_walking_islands, walking


def test_populated_walking_island_fails():
    points = [{"id": "a", "population": 10}, {"id": "b", "population": 20}]
    walks = [np.array([[0, 0], [1, 3601]]), np.array([[1, 0]])]
    with pytest.raises(ValueError, match="only their own"):
        check_walking_islands(points, walks)
    walks = [np.array([[0, 0], [1, 3600]]), np.array([[1, 0], [0, 3600]])]
    check_walking_islands(points, walks)


def test_exception_set_must_match_id_population_and_reason():
    points = [{"id": "a", "population": 10}, {"id": "b", "population": 20}]
    walks = [np.array([[0, 0]]), np.array([[1, 0], [0, 3600]])]
    expected = [
        {
            "id": "a",
            "population": 10,
            "reason": "only own populated area reachable by walking in 60 minutes",
        }
    ]
    check_walking_islands(points, walks, exceptions=expected)
    for changed in (
        [],
        [{**expected[0], "population": 11}],
        [{**expected[0], "id": "b"}],
        [{**expected[0], "reason": "no largest-component connector within 300 m"}],
    ):
        with pytest.raises(ValueError, match="differ from frozen"):
            check_walking_islands(points, walks, exceptions=changed)


def test_snap_uses_largest_component_with_300_metre_limit(tmp_path):
    # A tiny disconnected road is nearer, but cannot be the connector target.
    roads = []
    for i, (a, b, coords) in enumerate(
        [
            ("a", "b", [(-113.50, 53.50), (-113.49, 53.50)]),
            ("b", "c", [(-113.49, 53.50), (-113.48, 53.50)]),
            ("d", "e", [(-113.49, 53.501), (-113.489, 53.501)]),
        ]
    ):
        roads.append(
            {
                "centerlineid": str(i),
                "centerline_type": "Road",
                "functional_class_code": "Arterial-Class B (Non-Primary Highway, Truck Route)",
                "from_intersectionid": a,
                "to_intersectionid": b,
                "geometry": mapping(LineString(coords)),
            }
        )
    (tmp_path / "roads_selected.json").write_text(json.dumps(roads))
    points = [
        {"id": "near", "kind": "stop", "lon": -113.49, "lat": 53.501},
        {"id": "far", "kind": "stop", "lon": -113.49, "lat": 53.504},
        {
            "id": "moved",
            "kind": "dissemination_area",
            "population": 0,
            "lon": -113.49,
            "lat": 53.504,
            "geometry": mapping(box(-113.491, 53.501, -113.489, 53.505)),
        },
        {
            "id": "unchanged",
            "kind": "dissemination_area",
            "population": 0,
            "lon": -113.49,
            "lat": 53.501,
            "geometry": mapping(box(-113.491, 53.50, -113.489, 53.502)),
        },
    ]
    walks, _ = walking(
        points, {"stop_index": {}, "stops": points, "tables": {}}, tmp_path, tmp_path
    )
    snaps = json.loads((tmp_path / "walking_snaps.json").read_text())
    assert snaps[0]["connected"] and snaps[0]["snap_metres"] > 100
    assert snaps[0]["road_segment_index"] in (0, 1)
    assert not snaps[1]["connected"] and snaps[1]["snap_metres"] > 300
    assert walks[1].tolist() == [[1, 0]]
    assert json.loads((tmp_path / "walking.json").read_text())["included_segments"] == 3
    assert snaps[2]["moved"] and snaps[2]["connected"]
    assert snaps[2]["snap_metres"] <= 300 < snaps[2]["original_snap_metres"]
    assert points[2]["lat"] == 53.504
    assert snaps[2]["access_point"]["lat"] == pytest.approx(53.501, abs=1e-6)
    assert snaps[2]["added_walking_seconds"] > 200
    costs = dict(walks[2].tolist())
    assert costs[0] >= snaps[2]["added_walking_seconds"]
    assert not snaps[3]["moved"] and points[3]["lat"] == 53.501


def test_combined_timetable_does_not_use_extension():
    walk = np.array([[[10, 1], [20, 2]]])
    geometry = np.array([[[90, 4], [100, 5]]])
    scheduled = np.array([[[30, 2], [60, 3]]])
    values = timetable_components(walk, geometry, scheduled)
    np.testing.assert_array_equal(values.sum(axis=-1), scheduled)
    np.testing.assert_array_equal(values[..., 2], scheduled - walk - values[..., 1])
    assert np.all(values[..., 2] <= 0)
    with pytest.raises(RuntimeError, match="dominate"):
        timetable_components(walk, geometry, geometry + 1)


def test_origin_cohorts_exclude_only_moved_origins():
    # Destination counts are already computed with the complete destination population.
    values = np.array([[[100, 2], [200, 4]], [[400, 6], [600, 8]]])
    cohorts = origin_cohorts(values, np.array([10, 30]), np.array([True, False]))
    assert cohorts["moved_area_count"] == 1
    assert cohorts["moved_area_population"] == 10
    assert cohorts["all_areas"]["city_population_weighted_mean_access"] == [412.5, 6.0]
    assert cohorts["without_moved"]["city_population_weighted_mean_access"] == [500, 7]
    assert cohorts["without_moved"]["origin_area_count"] == 1
    assert cohorts["without_moved"]["origin_population"] == 30


def test_release_requires_successful_walking_validation(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        require_walking_validation(tmp_path)
    manifests = tmp_path / "data/manifests"
    manifests.mkdir(parents=True)
    path = manifests / "walking_validation.json"
    for status, count in [("failed", 16), ("passed", 1), ("failed", 0)]:
        path.write_text(json.dumps({"status": status, "walking_only_self_count": count}))
        with pytest.raises(RuntimeError, match="Release blocked"):
            require_walking_validation(tmp_path)
    exceptions = manifests / "walking_exceptions.json"
    write_json(exceptions, {"areas": []})
    checksum = digest(exceptions)
    write_json(manifests / "walking_exceptions_registration.json", {"sha256": checksum})
    write_json(
        path,
        {
            "status": "passed",
            "walking_only_self_count": 0,
            "islands": [],
            "failures": [],
            "exception_sha256": checksum,
        },
    )
    require_walking_validation(tmp_path)
    frozen = [
        {
            "id": "a",
            "population": 10,
            "reason": "only own populated area reachable by walking in 60 minutes",
        }
    ]
    write_json(exceptions, {"areas": frozen})
    checksum = digest(exceptions)
    write_json(manifests / "walking_exceptions_registration.json", {"sha256": checksum})
    write_json(
        path,
        {
            "status": "passed",
            "walking_only_self_count": 1,
            "islands": [{"id": "a", "population": 10}],
            "failures": frozen,
            "exception_sha256": checksum,
        },
    )
    require_walking_validation(tmp_path)
    write_json(exceptions, {"areas": [{"id": "unexpected"}]})
    with pytest.raises(RuntimeError, match="Release blocked"):
        require_walking_validation(tmp_path)
