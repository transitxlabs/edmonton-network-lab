"""Run the local release checks and record portable commands and log paths."""

import os
import subprocess
import time
from datetime import datetime

from network_lab.common import ROOT, space_guard, write_json


def main():
    space_guard()
    logs = ROOT / "work-tmp.noindex" / datetime.now().strftime("validation-%Y%m%d-%H%M%S")
    logs.mkdir(parents=True)
    runtime = os.path.relpath(os.environ.get("NETWORK_LAB_PYTHON", ".venv/bin/python"), ROOT)
    relative_logs = logs.relative_to(ROOT)
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        TMPDIR=str(ROOT / "work-tmp.noindex"),
        RUFF_CACHE_DIR=str(logs / "ruff-cache"),
        MYPY_CACHE_DIR=str(logs / "mypy-cache"),
    )
    checks = [
        ("lint", [runtime, "-m", "ruff", "check", "src", "tests", "scripts"]),
        ("format", [runtime, "-m", "ruff", "format", "--check", "src", "tests", "scripts"]),
        ("types", [runtime, "-m", "mypy", "src/network_lab"]),
        (
            "fixtures",
            [
                runtime,
                "-m",
                "pytest",
                "-q",
                f"--basetemp={relative_logs}/fixtures",
                "-o",
                f"cache_dir={relative_logs}/pytest-cache",
            ],
        ),
        ("frozen-inputs", [runtime, "scripts/verify_inputs.py"]),
        ("artifacts", [runtime, "scripts/check_artifacts.py"]),
    ]
    records = []
    for name, command in checks:
        space_guard()
        started = time.perf_counter()
        log = logs / f"{name}.log"
        with log.open("w") as stream:
            completed = subprocess.run(
                command, check=False, cwd=ROOT, env=env, stdout=stream, stderr=stream
            )
        records.append(
            {
                "check": name,
                "command": command,
                "exit_code": completed.returncode,
                "seconds": time.perf_counter() - started,
                "log": str(log.relative_to(ROOT)),
            }
        )
        write_json(
            ROOT / "results/local_checks.json",
            {
                "checks": records,
                "all_exit_zero": all(r["exit_code"] == 0 for r in records),
                "hosted_ci_executed": False,
            },
        )
        print(f"{name}: exit {completed.returncode}", flush=True)
        if completed.returncode:
            raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
