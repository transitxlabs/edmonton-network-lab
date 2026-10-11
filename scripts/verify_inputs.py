"""Check committed frozen inputs before offline rebuilding."""

import json

from network_lab.common import ROOT, digest, space_guard

space_guard()
for record in json.loads((ROOT / "data/manifests/sources.json").read_text()):
    path = ROOT / record["path"]
    if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
        raise SystemExit(f"Frozen input differs: {path.name}")
registration = ROOT / "data/manifests/protocol_registration.json"
if registration.exists():
    protocol = json.loads(registration.read_text())
    if digest(ROOT / "PROTOCOL_REALTIME.md") != protocol["sha256"]:
        raise SystemExit("Prospective protocol differs from its registration")
print("Frozen input checksums verified")
for document, name in [
    ("PROTOCOL_AMENDMENT_1.md", "protocol_amendment_1.json"),
    ("data/manifests/walking_exceptions.json", "walking_exceptions_registration.json"),
]:
    record = ROOT / "data/manifests" / name
    if record.exists() and digest(ROOT / document) != json.loads(record.read_text())["sha256"]:
        raise SystemExit(f"Frozen registration differs: {document}")
