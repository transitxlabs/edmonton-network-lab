"""Read-only archive metadata inventory. No payload decompression or service analysis."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from network_lab.common import ROOT, digest, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--archive", default=os.environ.get("ETS_RT_ARCHIVE"))
args = parser.parse_args()
if not args.archive:
    parser.error("provide --archive or set ETS_RT_ARCHIVE")
archive = Path(args.archive)
if not (archive / "data").is_dir() or not (archive / "logs").is_dir():
    parser.error("archive must contain data and logs directories")
cutoff = datetime.now(UTC) - timedelta(seconds=60)
start = datetime(2026, 10, 11, 9, 8, tzinfo=UTC)
files = []
for p in sorted((archive / "data").rglob("*.pb.gz")):
    timestamp = datetime.strptime(p.name.split(".")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    if start <= timestamp <= cutoff:
        files.append(
            {
                "path": str(p.relative_to(archive)),
                "bytes": p.stat().st_size,
                "compressed_sha256": digest(p),
                "timestamp_utc": timestamp.isoformat(),
                "feed": p.parent.name,
            }
        )
events = []
for p in sorted((archive / "logs").glob("fetch-*.tsv")):
    for row in csv.reader(p.read_text().splitlines(), delimiter="\t"):
        if len(row) < 2:
            continue
        timestamp = datetime.fromisoformat(row[0])
        if start <= timestamp <= cutoff:
            events.append(row)
status = Counter((r[1], r[2]) for r in events if len(r) >= 3 and r[1] != "START")
times = defaultdict(list)
gaps = []
for r in events:
    if len(r) >= 3 and r[1] not in ("START", "STOP"):
        t = datetime.fromisoformat(r[0])
        times[r[1]].append(t)
        if r[2].startswith("GAP_"):
            gaps.append({"timestamp_utc": r[0], "feed": r[1], "status": r[2]})
spacing = []
for feed, tt in times.items():
    for a, b in itertools.pairwise(tt):
        seconds = (b - a).total_seconds()
        if seconds > 60:
            spacing.append(
                {
                    "feed": feed,
                    "start_utc": a.isoformat(),
                    "end_utc": b.isoformat(),
                    "seconds_between_attempts": seconds,
                }
            )
protocol = ROOT / "PROTOCOL_REALTIME.md"
commit = subprocess.check_output(
    ["git", "log", "-1", "--format=%H", "--", str(protocol)], cwd=ROOT, text=True
).strip()
committed = subprocess.check_output(
    ["git", "show", "-s", "--format=%cI", commit], cwd=ROOT, text=True
).strip()
write_json(
    ROOT / "data/manifests/protocol_registration.json",
    {
        "sha256": digest(protocol),
        "commit": commit,
        "committed_at": committed,
        "payload_analysis_before_registration": False,
        "original_registration_commit": "826766f9d7fe7b662d5ff632a1d02f3b42e5efc1",
        "original_registration_sha256": "c0dc32c4a2fe58add292ee4239f27e5bb8b8a2d0fa17b55ee7cfeeaa80251684",
        "original_registration_time": "2026-10-11T02:12:15-07:00",
        "amendment": "Rank bootstrap p-value formula clarified before payload analysis or archive inventory",
    },
)
write_json(
    ROOT / "data/manifests/pilot_archive.json",
    {
        "label": "pilot; metadata only; no reliability inference",
        "archive_read_only": True,
        "payloads_decoded": 0,
        "collector_start_utc": start.isoformat(),
        "inventory_cutoff_utc": cutoff.isoformat(),
        "elapsed_hours": (cutoff - start).total_seconds() / 3600,
        "files": files,
        "file_count": len(files),
        "compressed_bytes": sum(x["bytes"] for x in files),
        "feed_file_counts": dict(Counter(x["feed"] for x in files)),
        "fetch_status_counts": [
            {"feed": k[0], "status": k[1], "count": v} for k, v in sorted(status.items())
        ],
        "logged_gaps": gaps,
        "attempt_spacings_over_60_seconds": spacing,
        "coverage_limit": "Counts describe collection. 304 responses have no stored body; their content is not assumed known. No absence is interpreted as a cancelled trip.",
        "sources": {
            "vehicle_positions": "https://gtfs.edmonton.ca/TMGTFSRealTimeWebService/Vehicle/VehiclePositions.pb",
            "trip_updates": "https://gtfs.edmonton.ca/TMGTFSRealTimeWebService/TripUpdate/TripUpdates.pb",
            "alerts": "https://gtfs.edmonton.ca/TMGTFSRealTimeWebService/Alert/Alerts.pb",
        },
        "licence": "Open Government Licence - Edmonton",
    },
)
with (ROOT / "data/manifests/pilot_fetch_log.tsv").open("w") as f:
    for row in events:
        f.write("\t".join(row) + "\n")
print(
    json.dumps(
        {
            "files": len(files),
            "bytes": sum(x["bytes"] for x in files),
            "logged_gaps": len(gaps),
            "payloads_decoded": 0,
        }
    )
)
