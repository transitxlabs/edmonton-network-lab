"""The required technical note remains within four to six printed pages."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader


def test_note_page_count(tmp_path):
    source = Path(__file__).resolve().parents[1] / "scripts/note.py"
    spec = importlib.util.spec_from_file_location("note_fixture", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    (tmp_path / "docs").mkdir()
    summary = {
        "routes": 243,
        "stops": 6790,
        "active_trip_occurrences": 12813,
        "service_date": "2026-10-13",
        "dissemination_areas": 1352,
        "population": 1010899,
        "library_destinations": 22,
        "route_deletions": 243,
        "full_recomputation_checks": 243,
        "city_population_weighted_mean_access": [[100000.5, 2], [300000.1, 6], [500000.3, 12]],
        "city_population_weighted_time_range": [
            [[10000.1, 1], [20000.2, 1], [30000.3, 1]],
            [[400000.1, 10], [500000.2, 15], [600000.3, 22]],
        ],
    }
    benchmark = {
        "full_seconds": 4500.12,
        "reuse_seconds": 750.43,
        "aggregate_speedup": 5.99,
        "base": {"wall_seconds": 27.7},
        "any_effect_speedup": 4.5,
        "any_effect_routes": 180,
        "top_five_speedups": [{"route_id": "a", "speedup": 1.5}],
    }
    summary["origin_cohorts"] = {
        "moved_area_count": 12,
        "moved_area_population": 5553,
        "without_moved": {
            "origin_area_count": 1340,
            "origin_population": 1005346,
            "city_population_weighted_mean_access": [[100550.5, 2], [301650.1, 6], [502750.3, 12]],
        },
    }
    oracle = {"matches": 2000, "queries": 2000, "reachable_queries": 700, "seed": 20261011}
    walking = {
        "included_segments": 49552,
        "unconnected_points": {"dissemination_area": 0},
        "moved_access_areas": 12,
        "moved_access_population": 5553,
        "exceptions": [
            {
                "id": f"2021S051248112{i:03}",
                "population": 400,
                "reason": "only own populated area reachable by walking in 60 minutes",
            }
            for i in range(7)
        ],
    }
    gtfs = {"published_trips": 86628, "rejected_records": 0}
    protocol = {"sha256": "0" * 64, "committed_at": "2026-10-11T02:39:08-07:00"}
    ranks = [
        {
            "route_id": f"fixture-{i}",
            "population_weighted_loss_45": str(12345 - i),
            "population_weighted_loss_30": str(8000 - i),
            "population_weighted_loss_60": str(18000 - i),
            "rank_45_min": 1,
            "rank_45_max": 20,
            "top_ten_departures_45": 10,
        }
        for i in range(10)
    ]
    module.note(
        summary,
        benchmark,
        oracle,
        walking,
        gtfs,
        protocol,
        ranks,
        {"sha256": "1" * 64, "registered_at": "2026-10-11T06:35:53-07:00"},
        {
            "top_five": {str(b): ranks[:5] for b in (30, 45, 60)},
            "rho_30_45": 0.945,
            "primary_routes": 180,
        },
    )
    pdf = PdfReader(tmp_path / "docs/TECHNICAL_NOTE.pdf")
    assert len(pdf.pages) == 6
    texts = [page.extract_text() for page in pdf.pages]
    assert all(len(text) > 500 for text in texts)
    assert "Contains information licensed under" in " ".join(texts)
    assert "Adapted from Statistics Canada" in " ".join(texts)


def test_render_rejects_failed_walking_before_changing_documents(tmp_path):
    import sys

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    spec = importlib.util.spec_from_file_location("render_fixture", scripts / "render.py")
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(scripts), *sys.path]):
        spec.loader.exec_module(module)
    module.ROOT = tmp_path
    manifests = tmp_path / "data/manifests"
    manifests.mkdir(parents=True)
    (manifests / "walking_validation.json").write_text(
        '{"status": "failed", "walking_only_self_count": 16}'
    )
    document = tmp_path / "README.md"
    document.write_text("Prior build, awaiting validation\n")
    with pytest.raises(RuntimeError, match="Release blocked"):
        module.render()
    assert document.read_text() == "Prior build, awaiting validation\n"
    assert not (tmp_path / "docs").exists()
