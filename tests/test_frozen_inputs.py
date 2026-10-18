"""The frozen inputs rebuild the published counts and manifests the README reports."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from network_lab.gtfs import load, occurrences
from network_lab.prepare import census

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "data/frozen"
MANIFESTS = ROOT / "data/manifests"


@pytest.fixture(scope="module")
def feed_and_ledger(tmp_path_factory):
    out = tmp_path_factory.mktemp("gtfs_manifests")
    return load(FROZEN / "ets_gtfs.zip", out), out


@pytest.fixture(scope="module")
def model_metadata():
    return json.loads((MANIFESTS / "model.json").read_text())


def test_frozen_feed_has_the_published_route_stop_and_trip_counts(feed_and_ledger):
    feed, _ = feed_and_ledger
    # README step 1: 243 routes, 6,790 stops and 86,628 trips.
    assert len(feed["routes"]) == 243
    assert len(feed["stops"]) == 6790
    assert len(feed["trips"]) == 86628
    assert len(feed["times"]) == 86628


@pytest.mark.parametrize(
    "name",
    [
        "gtfs.json",
        "calendar_expansion.json",
        "rejected_records.json",
        "time_range.json",
        "routing_feature_audit.json",
    ],
)
def test_feed_ingestion_rebuilds_committed_manifests_byte_for_byte(feed_and_ledger, name):
    _, out = feed_and_ledger
    assert (out / name).read_bytes() == (MANIFESTS / name).read_bytes()


def test_feed_ingestion_rejects_no_published_record(feed_and_ledger):
    _, out = feed_and_ledger
    manifest = json.loads((out / "gtfs.json").read_text())
    assert manifest["rejected_records"] == 0
    assert manifest["valid_trips"] == manifest["published_trips"] == 86628
    assert json.loads((out / "rejected_records.json").read_text()) == []


def test_service_day_occurrences_match_the_routed_model(feed_and_ledger, model_metadata):
    feed, _ = feed_and_ledger
    trips, ids = occurrences(feed, date(2026, 10, 13))
    assert model_metadata["service_date"] == "2026-10-13"
    assert len(trips) == len(ids) == model_metadata["trip_occurrences"] == 12813
    assert ids == model_metadata["trip_ids"]
    assert len(set(ids)) == len(ids)
    # Every occurrence comes from the service day or an adjacent date.
    assert {i.split(":", 1)[0] for i in ids} <= {"2026-10-12", "2026-10-13", "2026-10-14"}
    for trip in trips:
        times = [t for row in trip["rows"] for t in row[1:3]]
        assert times == sorted(times)
        assert 0 <= trip["route"] < 243


# census() uses shapely.ops.transform, which shapely 2.2 marks as deprecated.
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_census_reconciles_every_area_to_the_city_total():
    areas, control = census(FROZEN)
    # README step 2: all 1,352 dissemination areas; 1,010,899 Census residents.
    assert len(areas) == control["dissemination_areas"] == 1352
    assert sum(a["population"] for a in areas) == control["population"] == 1010899
    assert control == json.loads((MANIFESTS / "census.json").read_text())
    assert [a["id"] for a in areas] == sorted(a["id"] for a in areas)
    assert all(a["id"].startswith("2021S0512") for a in areas)


def test_model_destinations_are_areas_plus_22_libraries(model_metadata):
    libraries = json.loads((FROZEN / "libraries.json").read_text())
    ns, nda, npoints = model_metadata["nstops"], model_metadata["nda"], model_metadata["npoints"]
    assert (ns, nda, model_metadata["nroutes"]) == (6790, 1352, 243)
    assert npoints - ns - nda == len(libraries) == 22
    kinds = [p["kind"] for p in model_metadata["points"]]
    assert kinds == ["stop"] * ns + ["dissemination_area"] * nda + ["library"] * 22
    assert sum(p["population"] for p in model_metadata["points"][ns : ns + nda]) == 1010899
