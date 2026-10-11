"""Freeze the authorised walking exceptions before a full numerical rebuild."""

from datetime import datetime
from zoneinfo import ZoneInfo

from network_lab.common import ROOT, digest, write_json
from network_lab.prepare import prepare


def main():
    manifests = ROOT / "data/manifests"
    path = manifests / "walking_exceptions.json"
    registration = manifests / "walking_exceptions_registration.json"
    if path.exists() or registration.exists():
        raise SystemExit("Walking exception registration already exists; preserve it unchanged")
    validation = prepare(discover_exceptions=True)
    stamp = datetime.now(ZoneInfo("America/Vancouver")).isoformat()
    write_json(path, {"registered_at": stamp, "areas": validation["failures"]})
    write_json(registration, {"registered_at": stamp, "sha256": digest(path)})
    print(f"Frozen {len(validation['failures'])} walking exceptions at {stamp}")
    print(f"SHA-256 {digest(path)}")


if __name__ == "__main__":
    main()
