"""Small deterministic input and output helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def project_root() -> Path:
    source = Path(__file__).resolve().parents[2]
    candidates = [source, Path.cwd(), *Path.cwd().parents]
    for candidate in candidates:
        if (candidate / "data/manifests/sources.json").is_file():
            return candidate
    raise RuntimeError("Run from a checkout containing the frozen input manifest")


ROOT = project_root()
INF = 1_000_000_000


def space_guard() -> None:
    free = shutil.disk_usage("/").free
    if free < 25_000_000_000:
        raise RuntimeError(f"Free space below 25 GB: {free} bytes; work stopped")


def require_walking_validation(root: Path = ROOT) -> None:
    """Reject release work before reading results from a failed walking build."""
    path = root / "data/manifests/walking_validation.json"
    if not path.is_file():
        raise RuntimeError("Walking validation is missing; rebuild the walking model first")
    validation = json.loads(path.read_text())
    if validation.get("status") != "passed":
        raise RuntimeError(
            "Release blocked by walking validation: "
            f"{validation.get('walking_only_self_count', 'unknown')} populated areas "
            "reach only themselves in 60 minutes; prior results cannot validate this build"
        )
    exceptions = root / "data/manifests/walking_exceptions.json"
    registration = root / "data/manifests/walking_exceptions_registration.json"
    if not exceptions.is_file() or not registration.is_file():
        raise RuntimeError("Release blocked: frozen walking exception registration is missing")
    frozen = json.loads(exceptions.read_text())
    recorded = json.loads(registration.read_text())
    checksum = digest(exceptions)
    if (
        checksum != recorded["sha256"]
        or checksum != validation.get("exception_sha256")
        or validation.get("failures") != frozen["areas"]
        or validation.get("walking_only_self_count") != len(validation.get("islands", []))
    ):
        raise RuntimeError("Release blocked: walking failures differ from frozen exceptions")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
