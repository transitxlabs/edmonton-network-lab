"""Replay a clean local commit and compare every canonical numerical hash."""

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from network_lab.common import ROOT, digest, space_guard, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", default="results/replay_receipt.json")
    args = parser.parse_args()
    space_guard()
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    work = ROOT / "work-tmp.noindex"
    work.mkdir(exist_ok=True)
    checkout = work / datetime.now().strftime("replay-%Y%m%d-%H%M%S")
    # Fetch directly from the local repository without configuring a remote.
    subprocess.run(["git", "init", "--initial-branch=main", str(checkout)], check=True)
    subprocess.run(["git", "fetch", "--no-tags", str(ROOT), source], cwd=checkout, check=True)
    subprocess.run(["git", "checkout", "-B", "main", source], cwd=checkout, check=True)
    assert not subprocess.check_output(["git", "remote"], cwd=checkout, text=True).strip()
    clean = not subprocess.check_output(["git", "status", "--porcelain"], cwd=checkout, text=True)
    assert clean
    assert (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
        == source
    )
    with (checkout / ".git/info/exclude").open("a") as stream:
        stream.write("\nwork-tmp.noindex/\n")
    expected = json.loads((ROOT / "results/numerical_checksums.json").read_text())
    assert len(expected) >= 26
    initial = []
    for name, checksum in expected.items():
        path = checkout / "results" / name
        if path.is_file():
            assert digest(path) == checksum, name
            initial.append(name)
    runtime = Path(os.environ.get("NETWORK_LAB_PYTHON", str(ROOT / ".venv/bin/python")))
    if not runtime.is_absolute():
        runtime = ROOT / runtime
    relative_runtime = os.path.relpath(runtime, checkout)
    temporary = checkout / "work-tmp.noindex"
    temporary.mkdir()
    env = os.environ.copy()
    env.update(NETWORK_LAB_PYTHON=relative_runtime, TMPDIR=str(temporary))
    config = {
        "checkout": str(checkout.relative_to(ROOT)),
        "source_commit": source,
        "initial_checkout_clean": clean,
        "initial_artifact_hashes_verified": initial,
        "command": f"NETWORK_LAB_PYTHON={relative_runtime} ./rebuild.sh --replay",
        "runtime": os.path.relpath(runtime, ROOT),
        "runtime_relative_to": "source repository",
        "started_utc": datetime.now(UTC).isoformat(),
    }
    log = work / (checkout.name + ".log")
    config["log"] = str(log.relative_to(ROOT))
    receipt = ROOT / args.receipt
    write_json(receipt, config)
    started = time.perf_counter()
    with log.open("w") as stream:
        completed = subprocess.run(
            ["./rebuild.sh", "--replay"],
            check=False,
            cwd=checkout,
            env=env,
            stdout=stream,
            stderr=stream,
        )
    config.update(
        exit_code=completed.returncode,
        wall_seconds=time.perf_counter() - started,
        finished_utc=datetime.now(UTC).isoformat(),
    )
    if completed.returncode:
        config["all_numeric_hashes_match"] = False
        write_json(receipt, config)
        raise SystemExit(completed.returncode)
    actual = json.loads((checkout / "results/numerical_checksums.json").read_text())
    mismatches = {
        k: {"expected": expected.get(k), "actual": actual.get(k)}
        for k in expected.keys() | actual.keys()
        if expected.get(k) != actual.get(k)
    }
    config.update(
        hash_count=len(expected),
        mismatches=mismatches,
        all_numeric_hashes_match=not mismatches,
        canonical_checksums=actual,
        replay_artifact_checks=json.loads((checkout / "results/artifact_checks.json").read_text()),
        replay_full_deletion_checks=json.loads((checkout / "results/summary.json").read_text())[
            "full_recomputation_checks"
        ],
        timings_excluded_from_equality=True,
    )
    write_json(receipt, config)
    assert not mismatches, mismatches
    space_guard()
    print(f"Clean replay passed: {len(expected)} canonical hashes match", flush=True)


if __name__ == "__main__":
    main()
