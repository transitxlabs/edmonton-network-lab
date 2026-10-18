"""Strict GTFS ingestion: a row ledger for every rejection and a complete calendar."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from network_lab.gtfs import load

ROUTES = "route_id,route_long_name\nr1,One\nr2,Two\n"
STOPS = "stop_id,stop_lat,stop_lon\ns1,53.50,-113.50\ns2,53.51,-113.49\ns3,53.52,-113.48\n"
TRIPS = (
    "trip_id,route_id,service_id\n"
    "ok,r1,wk\n"
    "special,r2,extra\n"
    "badstop,r1,wk\n"
    "backwards,r1,wk\n"
    "flexible,r1,wk\n"
    "single,r1,wk\n"
    "overtaking,r1,wk\n"
    "orphan,r9,wk\n"
)
STOP_TIMES = (
    "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\n"
    "ok,08:00:00,08:00:00,s1,1,0,0\n"
    "ok,08:10:00,08:11:00,s2,2,0,0\n"
    "ok,25:30:00,25:30:00,s3,3,0,1\n"
    "special,09:00:00,09:00:00,s2,1,,\n"
    "special,09:05:00,09:05:00,s3,2,,\n"
    "badstop,08:00:00,08:00:00,s1,1,0,0\n"
    "badstop,08:05:00,08:05:00,s9,2,0,0\n"
    "backwards,08:00:00,08:00:00,s1,1,0,0\n"
    "backwards,08:06:00,08:05:00,s2,2,0,0\n"
    "flexible,08:00:00,08:00:00,s1,1,2,0\n"
    "flexible,08:05:00,08:05:00,s2,2,0,0\n"
    "single,08:00:00,08:00:00,s1,1,0,0\n"
    "overtaking,08:00:00,08:10:00,s1,1,0,0\n"
    "overtaking,08:05:00,08:05:00,s2,2,0,0\n"
    "orphan,08:00:00,08:00:00,s1,1,0,0\n"
    "orphan,08:05:00,08:05:00,s2,2,0,0\n"
    "ghost,08:00:00,08:00:00,s1,1,0,0\n"
)
CALENDAR = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
    "wk,1,1,1,1,1,0,0,20261001,20261231\n"
)
CALENDAR_DATES = (
    "service_id,date,exception_type\n"
    "extra,20261013,1\n"
    "wk,20261014,2\n"
    "wk,20261201,2\n"
    "wk,20261015,3\n"
)
FEED_INFO = "feed_publisher_name,feed_start_date,feed_end_date\nFixture,20261012,20261015\n"


def write_feed(path: Path, **overrides: str | None) -> Path:
    tables = {
        "routes": ROUTES,
        "stops": STOPS,
        "trips": TRIPS,
        "stop_times": STOP_TIMES,
        "calendar": CALENDAR,
        "calendar_dates": CALENDAR_DATES,
        "feed_info": FEED_INFO,
    }
    tables.update(overrides)
    with zipfile.ZipFile(path, "w") as z:
        for name, text in tables.items():
            if text is not None:
                z.writestr(name + ".txt", text)
    return path


@pytest.fixture
def ingested(tmp_path):
    out = tmp_path / "manifests"
    feed = load(write_feed(tmp_path / "feed.zip"), out)
    return feed, out


def test_only_complete_fixed_schedule_trips_are_routed(ingested):
    feed, _ = ingested
    assert sorted(feed["times"]) == ["ok", "special"]
    # Rows are ordered by stop sequence and keep stop index, times, pickup and drop-off.
    assert feed["times"]["ok"] == [
        [0, 28800, 28800, 0, 0],
        [1, 29400, 29460, 0, 0],
        [2, 91800, 91800, 0, 1],
    ]
    assert feed["times"]["special"][0] == [1, 32400, 32400, 0, 0]
    assert feed["route_index"] == {"r1": 0, "r2": 1}
    assert feed["stop_index"] == {"s1": 0, "s2": 1, "s3": 2}


def test_every_rejection_is_recorded_with_its_reason(ingested):
    _, out = ingested
    ledger = json.loads((out / "rejected_records.json").read_text())
    rows = {(r["table"], r.get("row"), r.get("trip_id"), r["reason"]) for r in ledger}
    assert ("stop_times", 8, None, "unknown stop identifier") in rows
    assert ("stop_times", 10, None, "arrival after departure") in rows
    assert (
        "stop_times",
        11,
        None,
        "conditional pickup or drop-off is outside fixed schedule model",
    ) in rows
    assert ("stop_times", 18, None, "unknown trip identifier") in rows
    for trip in ("badstop", "backwards", "flexible"):
        assert ("trips", None, trip, "trip contains a rejected stop-time record") in rows
    assert ("trips", None, "single", "trip has fewer than two timed stops") in rows
    assert ("trips", None, "overtaking", "non-monotone trip times") in rows
    assert ("trips", None, "orphan", "unknown route identifier") in rows
    assert ("calendar_dates", 4, None, "exception outside declared feed dates") in rows
    assert ("calendar_dates", 5, None, "invalid exception type") in rows
    manifest = json.loads((out / "gtfs.json").read_text())
    assert manifest["published_trips"] == 8
    assert manifest["valid_trips"] == 2
    assert manifest["rejected_records"] == len(ledger) == 12


def test_calendar_expansion_applies_weekdays_and_exceptions(ingested):
    feed, out = ingested
    assert feed["days"] == {
        "2026-10-12": {"wk"},
        "2026-10-13": {"wk", "extra"},
        "2026-10-14": set(),
        "2026-10-15": {"wk"},
    }
    expansion = json.loads((out / "calendar_expansion.json").read_text())
    assert expansion == [
        {"date": "2026-10-12", "services": ["wk"], "trips": ["ok"]},
        {"date": "2026-10-13", "services": ["extra", "wk"], "trips": ["ok", "special"]},
        {"date": "2026-10-14", "services": [], "trips": []},
        {"date": "2026-10-15", "services": ["wk"], "trips": ["ok"]},
    ]
    time_range = json.loads((out / "time_range.json").read_text())
    assert time_range["minimum_published_stop_time_seconds"] == 28800
    assert time_range["maximum_published_stop_time_seconds"] == 91800
    assert time_range["adjacent_service_dates_suffice_for_05_to_24_with_60_minute_horizon"]


@pytest.mark.parametrize("table", ["routes", "stops", "trips", "stop_times"])
def test_missing_required_table_is_fatal(tmp_path, table):
    with pytest.raises(ValueError, match=f"Missing required table: {table}"):
        load(write_feed(tmp_path / "feed.zip", **{table: None}), tmp_path / "out")


def test_duplicate_identifiers_and_bad_coordinates_are_fatal(tmp_path):
    with pytest.raises(ValueError, match="Duplicate route or stop"):
        load(write_feed(tmp_path / "a.zip", stops=STOPS + "s1,53.5,-113.5\n"), tmp_path / "a")
    with pytest.raises(ValueError, match="Duplicate trip"):
        load(write_feed(tmp_path / "b.zip", trips=TRIPS + "ok,r1,wk\n"), tmp_path / "b")
    with pytest.raises(ValueError, match="Invalid coordinates"):
        load(write_feed(tmp_path / "c.zip", stops=STOPS + "s4,91.0,-113.5\n"), tmp_path / "c")
