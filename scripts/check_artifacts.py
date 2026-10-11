"""Validate complete model coverage, monotonic deletions and reproducible outputs."""

import csv
import gzip
import hashlib
import json
import re
from html.parser import HTMLParser

import numpy as np
from pypdf import PdfReader

from network_lab.common import ROOT, digest, require_walking_validation, space_guard, write_json


class PageCheck(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.images = 0
        self.main = 0

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "main":
            self.main += 1
        if tag in ("script", "iframe"):
            raise AssertionError("Static page contains an executable or embedded external surface")
        if tag == "img":
            assert attrs.get("alt"), "Image needs a meaningful alternative"
            self.images += 1
        for field in ("href", "src"):
            if field in attrs:
                self.links.append(attrs[field])


space_guard()
require_walking_validation(ROOT)
results = ROOT / "results"
meta = json.loads((ROOT / "data/manifests/model.json").read_text())
design = json.loads((results / "design.json").read_text())
nda, nr = meta["nda"], meta["nroutes"]
nt = len(design["departures_seconds"])
access = np.load(results / "access_profiles.npz")["values"]
n1 = np.load(results / "n1_profiles.npz")["values"]
decomp = np.load(results / "decomposition.npz")["values"]
assert access.shape == (nda * nt, 3, 2)
assert n1.shape == (nr, nda * nt, 3, 2)
assert decomp.shape == (nda * nt, 3, 2, 3)
assert np.array_equal(decomp.sum(axis=-1), access)
assert np.all(decomp[..., :2] >= 0) and np.all(decomp[..., 2:] <= 0)
assert np.all(n1 >= 0) and np.all(n1 <= access)
assert np.all(access[:, 0, :] <= access[:, 1, :]) and np.all(access[:, 1, :] <= access[:, 2, :])
population = sum(p["population"] for p in meta["points"][meta["nstops"] : meta["nstops"] + nda])
assert population == design["origin_population"]
assert np.all(access[:, :, 0] <= population)
assert np.all(access[:, :, 1] <= meta["npoints"] - meta["nstops"] - nda)
ranking = list(csv.DictReader((results / "n1_ranking.csv").open()))
assert len(ranking) == nr
assert {r["route_id"] for r in ranking} == {r["route_id"] for r in meta["routes"]}
scores = [float(r["population_weighted_loss_45"]) for r in ranking]
assert scores == sorted(scores, reverse=True)
hourly = np.load(results / "route_hourly_ranks.npz")["ranks"]
assert hourly.shape == (nr, nt)
route_lookup = {r["route_id"]: i for i, r in enumerate(meta["routes"])}
for row in ranking:
    ranks = hourly[route_lookup[row["route_id"]]]
    assert int(row["rank_45_min"]) == ranks.min()
    assert int(row["rank_45_max"]) == ranks.max()
    assert int(row["top_ten_departures_45"]) == np.count_nonzero(ranks <= 10)
amendment = json.loads((ROOT / "data/manifests/protocol_amendment_1.json").read_text())
assert digest(ROOT / "PROTOCOL_AMENDMENT_1.md") == amendment["sha256"]
weights = np.repeat(
    [p["population"] for p in meta["points"][meta["nstops"] : meta["nstops"] + nda]], nt
)
summary = json.loads((results / "summary.json").read_text())
city_means = np.average(access, axis=0, weights=weights)
by_time = np.average(access.reshape(nda, nt, 3, 2), axis=0, weights=weights[::nt])
assert np.array_equal(city_means, summary["city_population_weighted_mean_access"])
cohorts = summary["origin_cohorts"]
moved = np.array(
    [p["access_point"]["moved"] for p in meta["points"][meta["nstops"] : meta["nstops"] + nda]]
)
assert cohorts["moved_area_count"] == int(moved.sum())
assert cohorts["moved_area_population"] == int(weights[::nt][moved].sum())
for name, mask in (("all_areas", np.ones(nda, dtype=bool)), ("without_moved", ~moved)):
    actual = np.average(access.reshape(nda, nt, 3, 2)[mask], axis=0, weights=weights[::nt][mask])
    assert np.array_equal(
        actual.mean(axis=0), cohorts[name]["city_population_weighted_mean_access"]
    )
    assert cohorts[name]["origin_area_count"] == int(mask.sum())
    assert cohorts[name]["origin_population"] == int(weights[::nt][mask].sum())
assert np.array_equal(
    [by_time.min(axis=0), by_time.max(axis=0)], summary["city_population_weighted_time_range"]
)
route_indices = {r["route_id"]: i for i, r in enumerate(meta["routes"])}
for row in ranking:
    index = route_indices[row["route_id"]]
    for j, threshold in enumerate([30, 45, 60]):
        for k, column in enumerate(
            ["population_weighted_loss_", "population_weighted_library_loss_"]
        ):
            assert float(row[column + str(threshold)]) == np.average(
                n1[index, :, j, k], weights=weights
            )
component_rows = list(csv.DictReader((results / "decomposition_area_summary.csv").open()))
assert len(component_rows) == nda * 3 * 2
assert (
    len({(r["origin"], r["budget_minutes"], r["destination_kind"]) for r in component_rows})
    == nda * 3 * 2
)
for row in component_rows:
    total = sum(float(row[c + "_mean"]) for c in ["walking", "geometry", "timetable"])
    assert abs(total - float(row["scheduled_mean"])) < 1e-7
oracle = json.loads((results / "oracle.json").read_text())
assert oracle["queries"] >= 2000 and oracle["matches"] == oracle["queries"]
timings = json.loads((results / "deletion_timings.json").read_text())
assert len(timings) == nr
assert sum(r["byte_equal"] is True for r in timings) >= 20
assert all(r["reuse_sha256"] for r in timings)
assert all(r["full_sha256"] == r["reuse_sha256"] for r in timings if r["full_sha256"])
frequency = json.loads((results / "frequency_checks.json").read_text())
assert (
    frequency["scenarios"] >= 20 and frequency["all_byte_equal"] and frequency["all_oracle_matched"]
)
assert sum(case["queries"] for case in frequency["cases"]) == frequency["query_batches"]
assert all(
    case["route_dependent_hourly_queries"] + case["uniform_minute_queries"] == case["queries"]
    for case in frequency["cases"]
)
page = PageCheck()
page.feed((ROOT / "docs/site/index.html").read_text())
assert page.main == 1 and page.images >= 3
for link in page.links:
    assert not re.match(r"^(https?:)?//", link), "Project page has an external resource"
    if link.startswith("#"):
        assert link[1:] in page.ids
    else:
        assert (ROOT / "docs/site" / link).resolve().is_file(), f"Missing local link: {link}"
pdf = PdfReader(ROOT / "docs/TECHNICAL_NOTE.pdf")
assert 4 <= len(pdf.pages) <= 6, f"Technical note has {len(pdf.pages)} pages"
texts = [p.extract_text() for p in pdf.pages]
assert all(t and len(t) > 200 for t in texts)
assert "Contains information licensed under" in " ".join(texts)
assert "Adapted from Statistics Canada" in " ".join(texts)
arrivals = np.load(results / "arrays/base_arrivals.npy", mmap_mode="r")
support = np.load(results / "arrays/route_support.npy", mmap_mode="r")
assert arrivals.shape == (nda * nt, meta["npoints"] - meta["nstops"])
assert support.shape == (nda * nt, nr)
np.savez_compressed(results / "base_results.npz", arrivals=arrivals, route_support=support)
certificates = 0
with gzip.open(results / "optimal_witnesses.jsonl.gz", "rt") as f:
    for line in f:
        cert = json.loads(line)
        assert cert["query"] == certificates
        legs = cert["legs"]
        destination = cert["destination_leg"]
        assert len(destination) == arrivals.shape[1]
        for i, leg in enumerate(legs):
            parent, trip, boarding, alighting, depart, arrive = leg
            assert -1 <= parent < i and 0 <= trip < len(meta["trip_ids"])
            assert 0 <= boarding < meta["nstops"] and 0 <= alighting < meta["nstops"]
            assert depart <= arrive
            if parent >= 0:
                assert legs[parent][5] <= depart
        if legs:
            ids = np.asarray(destination, dtype=np.int32)
            finite = ids >= 0
            assert np.all(ids[finite] < len(legs))
            leg_arrivals = np.asarray(legs, dtype=np.int64)[:, 5]
            assert np.all(leg_arrivals[ids[finite]] <= arrivals[certificates, finite])
        certificates += 1
assert certificates == nda * nt
canonical = [
    "design.json",
    "oracle.json",
    "access_profiles.csv",
    "access_summary.csv",
    "access_profiles.npz",
    "n1_profiles.npz",
    "n1_ranking.csv",
    "n1_area_summary.csv.gz",
    "decomposition.npz",
    "decomposition.json",
    "decomposition_area_summary.csv",
    "optimal_witnesses.jsonl.gz",
    "oracle_queries.csv",
    "map_legend.json",
    "spatial_quantiles.json",
]
canonical += ["frequency_queries.csv", "frequency_checks.json"]
canonical += ["base_results.npz", "ranking_sensitivity.json", "route_hourly_ranks.npz"]
checksums = {name: digest(results / name) for name in canonical}
checksums["base_arrival_values"] = hashlib.sha256(
    np.ascontiguousarray(arrivals).tobytes()
).hexdigest()
checksums["base_route_support"] = hashlib.sha256(
    np.ascontiguousarray(support).tobytes()
).hexdigest()
checksums["compiled_input_model"] = digest(ROOT / "build/model.bin")
checksums["input_index_manifest"] = digest(ROOT / "data/manifests/model.json")
checksums["protocol_amendment"] = digest(ROOT / "PROTOCOL_AMENDMENT_1.md")
for name in ["walking_exceptions.json", "walking_snaps.json"]:
    checksums[name] = digest(ROOT / "data/manifests" / name)
checksums["published_time_range"] = digest(ROOT / "data/manifests/time_range.json")
checksums["routing_feature_audit"] = digest(ROOT / "data/manifests/routing_feature_audit.json")
summary_values = {k: v for k, v in summary.items() if k != "full_recomputation_checks"}
checksums["summary_values"] = hashlib.sha256(
    json.dumps(summary_values, sort_keys=True).encode()
).hexdigest()
write_json(results / "numerical_checksums.json", checksums)
write_json(
    results / "artifact_checks.json",
    {
        "status": "passed",
        "area_departure_batches": nda * nt,
        "route_deletions": nr,
        "oracle_queries": oracle["queries"],
        "certificate_batches": certificates,
        "pdf_pages": len(pdf.pages),
        "local_links": len(page.links),
        "exact_decomposition_identity": True,
        "nonnegative_deletion_losses": True,
    },
)
print(
    f"Artifact checks passed: {certificates} certificate batches, {nr} routes, {len(pdf.pages)} note pages"
)
