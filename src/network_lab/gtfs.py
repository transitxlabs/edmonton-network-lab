"""Strict schedule ingestion with a row ledger and complete calendar expansion.

Copyright 2026 TransitX Labs Inc. Apache-2.0.
Calendar and schedule semantics follow the company's transit-access-audit;
this integer-second parser and ledger are newly written.
"""

from __future__ import annotations

import csv
import io
import itertools
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .common import digest, write_json


def seconds(value: str) -> int:
    if not re.fullmatch(r"\d{1,3}:\d{2}:\d{2}", value):
        raise ValueError("invalid time format")
    h, m, s = map(int, value.split(":"))
    if m >= 60 or s >= 60:
        raise ValueError("invalid minute or second")
    return h * 3600 + m * 60 + s


def load(path: Path, out: Path) -> dict[str, Any]:
    tables: dict[str, list[dict[str, str]]] = {}
    members: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if not n.endswith(".txt"):
                continue
            b = z.read(n)
            import hashlib

            rows = list(csv.DictReader(io.StringIO(b.decode("utf-8-sig"))))
            tables[n[:-4]] = rows
            members.append(
                {
                    "name": n,
                    "bytes": len(b),
                    "sha256": hashlib.sha256(b).hexdigest(),
                    "records": len(rows),
                }
            )
    for required in ("routes", "stops", "trips", "stop_times"):
        if not tables.get(required):
            raise ValueError(f"Missing required table: {required}")
    routes = sorted(tables["routes"], key=lambda r: r["route_id"])
    stops = sorted(tables["stops"], key=lambda r: r["stop_id"])
    ri = {r["route_id"]: i for i, r in enumerate(routes)}
    si = {s["stop_id"]: i for i, s in enumerate(stops)}
    if len(ri) != len(routes) or len(si) != len(stops):
        raise ValueError("Duplicate route or stop identifiers")
    for s in stops:
        lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"Invalid coordinates for {s['stop_id']}")
    trips = {t["trip_id"]: t for t in tables["trips"]}
    if len(trips) != len(tables["trips"]):
        raise ValueError("Duplicate trip identifier")
    times: dict[str, list[list[int]]] = defaultdict(list)
    invalid_trips: set[str] = set()
    pickup_counts: Counter[str] = Counter()
    drop_off_counts: Counter[str] = Counter()
    minimum_time, maximum_time = 1_000_000_000, 0
    for i, r in enumerate(tables["stop_times"], 2):
        try:
            if r["trip_id"] not in trips:
                raise ValueError("unknown trip identifier")
            if r["stop_id"] not in si:
                raise ValueError("unknown stop identifier")
            a, d = seconds(r["arrival_time"]), seconds(r["departure_time"])
            if a > d:
                raise ValueError("arrival after departure")
            p, q = int(r.get("pickup_type") or 0), int(r.get("drop_off_type") or 0)
            if p not in (0, 1) or q not in (0, 1):
                raise ValueError("conditional pickup or drop-off is outside fixed schedule model")
            times[r["trip_id"]].append([si[r["stop_id"]], a, d, p, q, int(r["stop_sequence"])])
            minimum_time, maximum_time = min(minimum_time, a, d), max(maximum_time, a, d)
            pickup_counts[str(p)] += 1
            drop_off_counts[str(q)] += 1
        except (ValueError, KeyError, TypeError) as e:
            rejected.append({"table": "stop_times", "row": i, "reason": str(e), "record": r})
            invalid_trips.add(r.get("trip_id", ""))
    valid: dict[str, list[list[int]]] = {}
    for tid, t in trips.items():
        try:
            if t["route_id"] not in ri:
                raise ValueError("unknown route identifier")
            rr = sorted(times.get(tid, []), key=lambda x: x[5])
            if tid in invalid_trips:
                raise ValueError("trip contains a rejected stop-time record")
            if len(rr) < 2:
                raise ValueError("trip has fewer than two timed stops")
            if len({x[5] for x in rr}) != len(rr):
                raise ValueError("duplicate stop sequence")
            if any(x[2] > y[1] for x, y in itertools.pairwise(rr)):
                raise ValueError("non-monotone trip times")
            valid[tid] = [x[:5] for x in rr]
        except ValueError as e:
            rejected.append({"table": "trips", "trip_id": tid, "reason": str(e), "record": t})
    info = tables.get("feed_info", [{}])[0]
    all_dates = [r["date"] for r in tables.get("calendar_dates", [])]
    start = date.fromisoformat(info.get("feed_start_date", min(all_dates)))
    end = date.fromisoformat(info.get("feed_end_date", max(all_dates)))
    days: dict[str, set[str]] = {}
    calendar_day = start
    while calendar_day <= end:
        active: set[str] = set()
        for r in tables.get("calendar", []):
            if r["start_date"] <= calendar_day.strftime("%Y%m%d") <= r["end_date"]:
                key = (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                )[calendar_day.weekday()]
                if r[key] == "1":
                    active.add(r["service_id"])
        days[calendar_day.isoformat()] = active
        calendar_day += timedelta(days=1)
    for i, r in enumerate(tables.get("calendar_dates", []), 2):
        try:
            exception_day = date.fromisoformat(r["date"]).isoformat()
            if exception_day not in days:
                raise ValueError("exception outside declared feed dates")
            if r["exception_type"] == "1":
                days[exception_day].add(r["service_id"])
            elif r["exception_type"] == "2":
                days[exception_day].discard(r["service_id"])
            else:
                raise ValueError("invalid exception type")
        except ValueError as e:
            rejected.append({"table": "calendar_dates", "row": i, "reason": str(e), "record": r})
    expansion = [
        {
            "date": d,
            "services": sorted(s),
            "trips": sorted(t for t, r in trips.items() if r["service_id"] in s and t in valid),
        }
        for d, s in sorted(days.items())
    ]
    write_json(out / "calendar_expansion.json", expansion)
    write_json(out / "rejected_records.json", rejected)
    manifest = {
        "feed_sha256": digest(path),
        "feed_info": info,
        "tables": members,
        "routes": len(routes),
        "stops": len(stops),
        "published_trips": len(trips),
        "valid_trips": len(valid),
        "rejected_records": len(rejected),
        "rejection_reasons": dict(Counter(x["reason"] for x in rejected)),
    }
    write_json(out / "gtfs.json", manifest)
    write_json(
        out / "time_range.json",
        {
            "minimum_published_stop_time_seconds": minimum_time,
            "maximum_published_stop_time_seconds": maximum_time,
            "stop_time_records": len(tables["stop_times"]),
            "pickup_types": dict(pickup_counts),
            "drop_off_types": dict(drop_off_counts),
            "adjacent_service_dates_suffice_for_05_to_24_with_60_minute_horizon": maximum_time
            < 53 * 3600,
        },
    )
    restricted_fields = {
        "transfers": ["from_route_id", "to_route_id", "from_trip_id", "to_trip_id"],
        "trips": ["continuous_pickup", "continuous_drop_off"],
        "routes": ["continuous_pickup", "continuous_drop_off"],
        "stop_times": [
            "continuous_pickup",
            "continuous_drop_off",
            "pickup_booking_rule_id",
            "drop_off_booking_rule_id",
            "location_group_id",
            "location_id",
            "start_pickup_drop_off_window",
            "end_pickup_drop_off_window",
        ],
    }
    feature_audit: dict[str, Any] = {"frequency_records": len(tables.get("frequencies", []))}
    for table, fields in restricted_fields.items():
        rows = tables.get(table, [])
        feature_audit[table + ".txt"] = {
            "records": len(rows),
            "nonblank_restricted_fields": {
                field: sum(bool(r.get(field, "").strip()) for r in rows)
                if rows and field in rows[0]
                else 0
                for field in fields
            },
        }
        if table == "transfers":
            feature_audit[table + ".txt"]["transfer_types"] = dict(
                Counter(r.get("transfer_type") or "0" for r in rows)
            )
    write_json(out / "routing_feature_audit.json", feature_audit)
    return {
        "tables": tables,
        "routes": routes,
        "stops": stops,
        "trips": trips,
        "times": valid,
        "days": days,
        "route_index": ri,
        "stop_index": si,
    }


def occurrences(feed: dict[str, Any], service_day: date) -> tuple[list[dict[str, Any]], list[str]]:
    """Include adjacent service dates so midnight and long trips are represented."""
    # A service date two days earlier could reach 05:00 only at 53:00 or later.
    # Reject that unsupported input instead of silently omitting a long trip.
    if any(rows[-1][2] >= 53 * 3600 for rows in feed["times"].values()):
        raise ValueError("Published trip beyond adjacent-date expansion window")
    result: list[dict[str, Any]] = []
    ids: list[str] = []
    for delta in (-1, 0, 1):
        day = (service_day + timedelta(days=delta)).isoformat()
        active = feed["days"].get(day, set())
        for tid, rr in sorted(feed["times"].items()):
            t = feed["trips"][tid]
            if t["service_id"] not in active:
                continue
            rows = [[s, a + delta * 86400, d + delta * 86400, p, q] for s, a, d, p, q in rr]
            if rows[-1][1] < 5 * 3600 or rows[0][2] > 25 * 3600:
                continue
            ids.append(f"{day}:{tid}")
            result.append({"route": feed["route_index"][t["route_id"]], "rows": rows})
    return result, ids
