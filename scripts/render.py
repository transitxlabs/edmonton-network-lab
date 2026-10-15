"""Static accessible charts, summaries, technical note and rebuild instructions."""

import csv
import html
import json
import shutil

import numpy as np
from note import fmt, note
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from network_lab.common import ROOT, require_walking_validation, write_json

PALETTE = ["#e7f1f0", "#b7d9d1", "#73b7a8", "#348774", "#155744"]


def svg(title, desc, width, height):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{html.escape(title)}</title><desc id="desc">{html.escape(desc)}</desc>',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<g font-family="Arial,sans-serif" fill="#173342">',
    ]


def map_chart(meta, values, site):
    ns, nda = meta["nstops"], meta["nda"]
    areas = meta["points"][ns : ns + nda]
    project = Transformer.from_crs(4326, 26912, always_xy=True).transform
    geometries = [transform(project, shape(a["geometry"])) for a in areas]
    lowx, lowy = min(g.bounds[0] for g in geometries), min(g.bounds[1] for g in geometries)
    highx, highy = max(g.bounds[2] for g in geometries), max(g.bounds[3] for g in geometries)
    scale = min(720 / (highx - lowx), 660 / (highy - lowy))
    cuts = np.quantile(values, [0, 0.2, 0.4, 0.6, 0.8, 1])
    lines = svg(
        "Scheduled 45-minute access by dissemination area",
        "Mean reachable people across twenty hourly departures. Every City dissemination area is included. Darker green denotes higher access. Complete values are available in the CSV.",
        760,
        760,
    )

    def xy(x, y):
        return 20 + (x - lowx) * scale, 680 - (y - lowy) * scale

    def path(g):
        if g.geom_type == "Polygon":
            rings = [g.exterior] + list(g.interiors)
            return " ".join(
                "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in [xy(*c) for c in ring.coords]) + " Z"
                for ring in rings
            )
        return " ".join(
            path(c)
            for c in g.geoms
            if c.geom_type in ("Polygon", "MultiPolygon", "GeometryCollection")
        )

    for i, g in enumerate(geometries):
        level = min(4, int(np.searchsorted(cuts[1:-1], values[i], side="right")))
        lines.append(
            f'<path d="{path(g)}" fill="{PALETTE[level]}" fill-rule="evenodd" stroke="#fff" stroke-width=".35"><title>{areas[i]["id"]}: {fmt(values[i])} reachable people</title></path>'
        )
    for p in meta["points"][ns + nda :]:
        x, y = xy(*project(p["lon"], p["lat"]))
        lines.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.3" fill="#b65d26"><title>{html.escape(p["name"])}</title></circle>'
        )
    for i in range(5):
        x = 20 + i * 145
        lines.append(
            f'<rect x="{x}" y="710" width="30" height="14" fill="{PALETTE[i]}"/><text x="{x}" y="745" font-size="11">{fmt(cuts[i])} to {fmt(cuts[i + 1])}</text>'
        )
    (site / "access-map.svg").write_text("\n".join(lines + ["</g></svg>"]))
    write_json(
        ROOT / "results/map_legend.json",
        {
            "threshold_minutes": 45,
            "statistic": "hourly mean",
            "quintile_breaks_reachable_population": cuts.tolist(),
        },
    )


def rank_chart(ranking, site):
    values = [float(r["population_weighted_loss_45"]) for r in ranking[:10]]
    maximum = max(values) or 1
    lines = svg(
        "Route deletion ranking at 45 minutes",
        "Ten largest population-weighted losses in reachable people per origin resident, averaged across hourly departures. All routes are in the CSV.",
        900,
        520,
    )
    for i, (r, v) in enumerate(zip(ranking[:10], values)):
        y = 25 + i * 47
        width = v / maximum * 550
        lines.append(
            f'<text x="20" y="{y + 21}" font-size="16">{html.escape(r["route_id"])}</text><rect x="125" y="{y}" width="{width:.2f}" height="29" rx="3" fill="#247f6b"/><text x="{135 + width:.2f}" y="{y + 21}" font-size="15">{fmt(v, 1)}</text>'
        )
    (site / "route-ranking.svg").write_text(
        "\n".join(
            lines
            + [
                '<text x="125" y="510" font-size="13">Mean reachable people lost per origin resident</text></g></svg>'
            ]
        )
    )


def day_chart(values, population, departures, site):
    means = np.average(values, axis=0, weights=population)
    maximum = float(means[:, :, 0].max()) or 1
    lines = svg(
        "Access through the scheduled day",
        "Population-weighted mean reachable people at twenty hourly samples, for three travel-time budgets. Connecting lines are visual guides, not minute-level estimates.",
        900,
        390,
    )
    for tick in range(5):
        y = 315 - tick * 65
        lines.append(
            f'<path d="M85,{y} H875" stroke="#dce5e8"/><text x="5" y="{y + 4}" font-size="12">{fmt(maximum * tick / 4)}</text>'
        )
    for j, c in enumerate(["#155744", "#467aa1", "#b15e26"]):
        coords = []
        for i, _ in enumerate(departures):
            x = 85 + i / (len(departures) - 1) * 790
            y = 315 - means[i, j, 0] / maximum * 260
            coords.append(f"{x:.2f},{y:.2f}")
            lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{c}"/>')
        lines.append(
            f'<polyline points="{" ".join(coords)}" stroke="{c}" fill="none" stroke-width="2"/>'
        )
        lines.append(
            f'<rect x="{85 + j * 210}" y="15" width="18" height="4" fill="{c}"/><text x="{110 + j * 210}" y="24" font-size="14">{[30, 45, 60][j]} minutes</text>'
        )
    for i in range(0, len(departures), 3):
        x = 85 + i / (len(departures) - 1) * 790
        lines.append(
            f'<text x="{x - 15:.2f}" y="343" font-size="12">{departures[i] // 3600:02}:00</text>'
        )
    lines.append('<text x="860" y="343" font-size="12">24:00</text>')
    (site / "day-profile.svg").write_text(
        "\n".join(
            lines
            + [
                '<text x="85" y="378" font-size="12">Hourly departure samples; 24:00 is next-day midnight</text></g></svg>'
            ]
        )
    )


def render():
    require_walking_validation(ROOT)
    results = ROOT / "results"
    read = lambda p: json.loads(p.read_text())
    meta = read(ROOT / "data/manifests/model.json")
    s = read(results / "summary.json")
    b = read(results / "benchmark.json")
    o = read(results / "oracle.json")
    w = read(ROOT / "data/manifests/walking.json")
    exceptions = read(ROOT / "data/manifests/walking_exceptions.json")
    exception_population = sum(r["population"] for r in exceptions["areas"])
    exception_rows = "".join(
        f'<tr><th scope="row">{r["id"]}</th><td>{fmt(r["population"])}</td><td>{html.escape(r["reason"])}</td></tr>'
        for r in exceptions["areas"]
    )
    exception_markdown = "\n".join(
        f"| {r['id']} | {fmt(r['population'])} | {r['reason']} |" for r in exceptions["areas"]
    )
    g = read(ROOT / "data/manifests/gtfs.json")
    p = read(ROOT / "data/manifests/protocol_registration.json")
    a = read(ROOT / "data/manifests/protocol_amendment_1.json")
    sensitivity = read(results / "ranking_sensitivity.json")
    if b["aggregate_speedup"] is None:
        b = read(results / "reference_benchmark.json")
    site = ROOT / "docs/site"
    (site / "data").mkdir(parents=True, exist_ok=True)
    departures = read(results / "design.json")["departures_seconds"]
    nda, ns = meta["nda"], meta["nstops"]
    values = np.load(results / "access_profiles.npz")["values"].reshape(nda, len(departures), 3, 2)
    population = np.array([p["population"] for p in meta["points"][ns : ns + nda]])
    rows = []
    for i in range(nda):
        row = {"origin": meta["points"][ns + i]["id"], "origin_population": int(population[i])}
        for j, t in enumerate([30, 45, 60]):
            for k, kind in enumerate(["population", "libraries"]):
                v = values[i, :, j, k]
                row[f"{kind}_{t}_mean"] = float(v.mean())
                row[f"{kind}_{t}_min"] = int(v.min())
                row[f"{kind}_{t}_max"] = int(v.max())
        rows.append(row)
    with (results / "access_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    components = np.load(results / "decomposition.npz")["values"].reshape(
        nda, len(departures), 3, 2, 3
    )
    component_means = components.mean(axis=1)
    with (results / "decomposition_area_summary.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "origin",
                "origin_population",
                "budget_minutes",
                "destination_kind",
                "walking_mean",
                "geometry_mean",
                "timetable_mean",
                "scheduled_mean",
            ]
        )
        for i in range(nda):
            for j, threshold in enumerate([30, 45, 60]):
                for k, kind in enumerate(["population", "libraries"]):
                    writer.writerow(
                        [
                            meta["points"][ns + i]["id"],
                            int(population[i]),
                            threshold,
                            kind,
                            *component_means[i, j, k],
                            float(values[i, :, j, k].mean()),
                        ]
                    )
    write_json(
        results / "spatial_quantiles.json",
        {
            "quantiles": [0, 0.25, 0.5, 0.75, 1],
            "values": np.quantile(values.mean(axis=1), [0, 0.25, 0.5, 0.75, 1], axis=0).tolist(),
            "interpretation": "DA quantiles of hourly means; not confidence intervals",
        },
    )
    ranking = list(csv.DictReader((results / "n1_ranking.csv").open()))
    map_chart(meta, values[:, :, 1, 0].mean(axis=1), site)
    rank_chart(ranking, site)
    day_chart(values, population, departures, site)
    for name in ["n1_ranking.csv", "access_summary.csv", "access_profiles.csv"]:
        shutil.copyfile(results / name, site / "data" / name)
    for name in ["walking_exceptions.json", "walking_snaps.json"]:
        shutil.copyfile(ROOT / "data/manifests" / name, site / "data" / name)
    note(s, b, o, w, g, p, ranking, a, sensitivity)
    upper = 100 * (1 - 0.05 ** (1 / o["reachable_queries"]))
    top = "".join(
        f'<tr><th scope="row">{r["rank"]}</th><td>{html.escape(r["route_id"])}</td><td>{html.escape(r["route_name"])}</td><td class="numeric">{fmt(float(r["population_weighted_loss_45"]), 1)}</td><td>{r["rank_45_min"]} to {r["rank_45_max"]}</td><td>{r["top_ten_departures_45"]}/20</td></tr>'
        for r in ranking[:10]
    )
    budget_tables = "".join(
        f"<div><h3>{budget}-minute top five</h3><ol>"
        + "".join(
            f"<li>{html.escape(r['route_id'])}: {fmt(float(r[f'population_weighted_loss_{budget}']), 1)}</li>"
            for r in sensitivity["top_five"][str(budget)]
        )
        + "</ol></div>"
        for budget in (30, 60)
    )
    top_speedups = "; ".join(
        f"{r['route_id']}: {r['speedup']:.2f}x" for r in b["top_five_speedups"]
    )
    cohorts = s["origin_cohorts"]
    unchanged = cohorts["without_moved"]
    cohort_intro = (
        f"Sensitivity excludes the {cohorts['moved_area_count']} moved-point origins "
        f"({fmt(cohorts['moved_area_population'])} residents), leaving "
        f"{fmt(unchanged['origin_area_count'])} origins ({fmt(unchanged['origin_population'])} residents). "
        "Both calculations retain every destination and its population; each averages twenty "
        "departures and weights included origins by Census population."
    )
    cohort_rows = ""
    cohort_markdown = "| Budget | All origins: people / libraries | Without moved origins: people / libraries |\n| --- | ---: | ---: |\n"
    for j, budget in enumerate((30, 45, 60)):
        all_values = cohorts["all_areas"]["city_population_weighted_mean_access"][j]
        without = unchanged["city_population_weighted_mean_access"][j]
        all_label = f"{fmt(all_values[0], 1)} / {fmt(all_values[1], 2)}"
        without_label = f"{fmt(without[0], 1)} / {fmt(without[1], 2)}"
        cohort_rows += f'<tr><th scope="row">{budget} minutes</th><td>{all_label}</td><td>{without_label}</td></tr>'
        cohort_markdown += f"| {budget} minutes | {all_label} | {without_label} |\n"
    stats = "".join(
        f"<div><strong>{fmt(v)}</strong><span>{label}</span></div>"
        for v, label in [
            (s["routes"], "published routes"),
            (s["dissemination_areas"], "dissemination areas"),
            (s["population"], "Census residents"),
        ]
    )
    page = f"""<!doctype html>
<html lang="en-CA"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Reproducible scheduled transit accessibility and route-deletion experiments on Edmonton public data.">
<title>Edmonton Network Lab | TransitX Labs</title><link rel="stylesheet" href="styles.css"></head>
<body><a class="skip" href="#main">Skip to content</a>
<header><a class="brand" href="#main">TRANSITX <span>LABS</span></a><nav aria-label="Sections"><a href="#atlas">Atlas</a><a href="#routes">Route changes</a><a href="#method">Method</a><a href="#limits">Limits</a></nav></header>
<main id="main" tabindex="-1"><section class="hero"><p class="eyebrow">Edmonton Network Lab / phase 2</p><h1>What changes when<br>transit service disappears?</h1>
<p class="lead">A reproducible view of scheduled access across Edmonton. Every dissemination area. Every published route deletion. Results checked against an independent calculation.</p>
<p class="scope">Schedule for {s["service_date"]} · Hourly departures, 05:00 to 24:00 · Walking graph proxy</p><div class="stats">{stats}</div></section>
<section class="evidence" aria-label="Verification"><p><strong>{o["matches"]}/{o["queries"]}</strong> independent routing queries matched; {o["reachable_queries"]} reachable, 0 disagreements (95% upper bound {upper:.2f}% on reachable queries).</p><p><strong>{s["full_recomputation_checks"]}/{s["route_deletions"]}</strong> deletion results matched full reruns byte for byte.</p><p><strong>{fmt(b["aggregate_speedup"], 2)}x</strong> aggregate measured deletion speedup with exact reuse; {fmt(b["any_effect_speedup"], 2)}x over {b["any_effect_routes"]} routes with any effect. Highest-loss five: {top_speedups}.</p></section>
<section id="atlas"><div class="intro"><p class="eyebrow">01 / The accessibility atlas</p><h2>How much of the city is within reach?</h2><p>Reachable population counts residents of destination areas whose representative points can be reached within the time budget. It measures scheduled opportunities, with no demand or ridership data.</p></div>
<div class="atlas-grid"><figure><img src="access-map.svg" alt="Every Edmonton dissemination area, coloured by mean 45-minute population access. Complete accessible values are in the linked CSV."><figcaption>45-minute access, mean of hourly departures. Orange points show libraries; colours show DA quintiles.</figcaption></figure>
<aside><h3>Citywide 45-minute access</h3><p class="big">{fmt(s["city_population_weighted_mean_access"][1][0])}</p><p>mean reachable people per origin resident, weighted by Census population.</p><p>Hourly city range: {fmt(s["city_population_weighted_time_range"][0][1][0])} to {fmt(s["city_population_weighted_time_range"][1][1][0])}.</p><p>This range describes twenty samples. It is not a confidence interval or a minute-level profile.</p><a class="button" href="data/access_summary.csv" download>Every area's summary (CSV)</a></aside></div>
<figure class="wide"><img src="day-profile.svg" alt="Citywide access at hourly departures for 30-, 45- and 60-minute budgets. Complete values are in the hourly CSV."><figcaption>Lines connect evaluated samples as visual guides. No values between samples are inferred. <a href="data/access_profiles.csv" download>Hourly profiles (CSV).</a></figcaption></figure></section>
<section aria-label="Moved-point sensitivity"><h2>City figures without moved-point origins</h2><p>{cohort_intro}</p><div class="table-wrap"><table><caption>Mean reachable people and libraries</caption><thead><tr><th scope="col">Budget</th><th scope="col">All origins: people / libraries</th><th scope="col">Without moved origins: people / libraries</th></tr></thead><tbody>{cohort_rows}</tbody></table></div></section>
<section id="routes"><div class="intro"><p class="eyebrow">02 / Every route, one deletion at a time</p><h2>Where does access depend on service?</h2><p>Each scenario removes one route while keeping walking and remaining schedules fixed. Origins are weighted by Census population, and losses averaged over the same hourly departures.</p></div>
<figure class="wide"><img src="route-ranking.svg" alt="Top ten population-weighted 45-minute access losses. The numerical ranking follows."><figcaption>Mean reachable people lost per origin resident, not passengers.</figcaption></figure>
<div class="table-wrap"><table><caption>Top ten of {s["routes"]} published route deletions under the 45-minute measure</caption><thead><tr><th scope="col">Rank</th><th scope="col">Route</th><th scope="col">Published route name</th><th scope="col">45-minute loss</th><th scope="col">Hourly rank range</th><th scope="col">Departures in top ten</th></tr></thead><tbody>{top}</tbody></table></div>
<div class="cards">{budget_tables}</div><p>Hourly ranks use route identifiers to break ties; top-ten counts are out of twenty departures. Budget reference correlation (30 versus 45): {sensitivity["rho_30_45"]:.3f} over {sensitivity["primary_routes"]} routes with non-zero population loss at 30 or 45 minutes.</p><p><a class="button" href="data/n1_ranking.csv" download>Complete N-1 ranking (CSV)</a></p></section>
<section id="method"><div class="intro"><p class="eyebrow">03 / A checkable calculation</p><h2>Keep the assumptions. Rebuild the result.</h2></div><div class="cards">
<article><h3>Independent calculation</h3><p>A compiled round-based engine is compared with a separately written connection scan on random queries. Fixtures also use a journey enumerator.</p></article>
<article><h3>Exact deletion reuse</h3><p>Deleting service shrinks feasible journeys. A selected optimum that survives certifies the same arrival. Affected batches are rerouted and checked against full calculations.</p></article>
<article><h3>Geometry and timetable</h3><p>Walking plus zero-wait geometry plus the signed timetable component equals scheduled access. Headway and span are combined because the extension rule creates artificial all-day service for short patterns.</p></article></div>
<p><a href="../TECHNICAL_NOTE.pdf">Six-page technical note (PDF)</a> · <a href="../TECHNICAL_NOTE.md">Markdown</a> · <a href="../REUSE_PROOF.md">Deletion proof</a></p></section>
<section id="limits"><p class="eyebrow">04 / Boundaries of the result</p><h2>Scheduled access, with stated limits.</h2><ul>
<li>Hourly samples cover one weekday; between-sample effects and other days may differ.</li><li>Road centrelines approximate walking. Crossings, barriers, entrances, mobility constraints and pathway times remain uncertain.</li><li>Census populations use one interior point per area. Points snap to the largest road component within 300 m. If this fails, the nearest point of the official polygon is used when its connector is within 300 m. Original-to-access straight distance adds walking time at 1.33 m/s on access and egress; original coordinates remain recorded. Stops without a connector serve only as on-board stops.</li><li>At 1.33 m/s, walking may overstate access for older people and in winter. Integer-ceiling times and omitted trails, walkways and footbridges understate reach. Roads without sidewalks, retained ramp and collector-distributor segments and straight links that ignore barriers may overstate reach. The City's segment-type field marks 820 ramp and collector-distributor segments (733 of them Arterial-Class B). They are retained as walkable, which may overstate reach near interchanges.</li><li>Libraries are selected destinations. Opening hours and capacity do not constrain this metric.</li><li>No demand, ridership, fare or capacity claims. Exact reuse refers to this frozen routing model.</li><li>The prospective real-time comparison awaits twenty eligible weekdays, capped at 45 complete service days. The pilot supports no reliability finding.</li></ul>
<p>The 12 moved access points are 592 m to 4,329 m from their interior points, adding 446 s to 3,256 s (about 7 to 54 minutes) of walking. {w["moved_access_areas"]} areas ({fmt(w["moved_access_population"])} residents) moved their access point. The frozen {len(exceptions["areas"])} exceptions ({fmt(exception_population)} residents) remain in every denominator with access computed as is. The build requires this exact failure set and rejects any different set. <a href="data/walking_exceptions.json">Frozen list (JSON)</a>; <a href="data/walking_snaps.json">Original points, access points and connector times (JSON)</a>.</p>
<div class="table-wrap"><table><caption>Frozen walking exceptions</caption><thead><tr><th scope="col">Area ID</th><th scope="col">Population</th><th scope="col">Reason</th></tr></thead><tbody>{exception_rows}</tbody></table></div>
<p>This public research release (2026-10-13) has no City endorsement.</p></section></main>
<footer><p><strong>TransitX Labs Inc.</strong> / Open, reproducible transit planning research.</p><p>Contains information licensed under the Open Government Licence – City of Edmonton.</p>
<p>Adapted from Statistics Canada, 2021 Census of Population, 2021. This does not constitute an endorsement by Statistics Canada of this product.</p>
<p><a href="../../DATA.md">Data and licences</a> · <a href="../../PROTOCOL_REALTIME.md">Prospective protocol</a> · <a href="../../PROTOCOL_AMENDMENT_1.md">Frozen amendment</a> · <a href="../../README.md">Rebuild instructions</a></p></footer></body></html>"""
    (site / "index.html").write_text(page)
    text = f"""# Edmonton Network Lab

Scheduled what-if accessibility across Edmonton's published network, with exact
reuse for service deletions. TransitX Labs Inc. produced this
public research release (2026-10-13) to make neighbourhood access changes
checkable and reproducible. There is no City endorsement.

The frozen feed contains **{s["routes"]} routes, {fmt(s["stops"])} stops and
{fmt(g["published_trips"])} published trips**. No route, stop or origin sampling
is applied. Service day **{s["service_date"]}** uses {fmt(s["active_trip_occurrences"])}
active trip occurrences, including the midnight boundary. All
**{fmt(s["dissemination_areas"])} City dissemination areas**, representing
**{fmt(s["population"])} Census residents**, are origins and population destinations.
There are {s["library_destinations"]} selected public library destinations.

Departures are evaluated **hourly from 05:00 through 24:00**, twenty samples per
origin and {fmt(s["dissemination_areas"] * 20)} origin/departure batches. The full minute
grid was projected beyond the report deadline from measured pilots;
`results/design.json` records the reason. No between-sample values are inferred.

## Measured results

| Check | Result | Denominator |
| --- | --- | --- |
| Independent connection scan | {o["match_rate"]:.0%} match | {o["queries"]} random queries; {o["reachable_queries"]} reachable; 0 disagreements; reachable-query 95% upper bound {upper:.2f}% |
| Reuse versus full rerun | Byte-identical | {s["full_recomputation_checks"]} full checks; all {s["route_deletions"]} routes evaluated |
| Deletion runtime | {fmt(b["full_seconds"], 2)} s full; {fmt(b["reuse_seconds"], 2)} s reuse | Four workers, all routes, loaded model |
| Aggregate measured speedup | {fmt(b["aggregate_speedup"], 2)}x; {fmt(b["any_effect_speedup"], 2)}x on {b["any_effect_routes"]} routes with any effect | Ratio of summed wall times; highest-loss five: {top_speedups} |

| Budget | Mean reachable people per origin resident | Hourly range, people | Mean reachable libraries | Hourly range, libraries |
| --- | --- | --- | --- | --- |
"""
    for j, t in enumerate([30, 45, 60]):
        text += f"| {t} minutes | {fmt(s['city_population_weighted_mean_access'][j][0], 1)} | {fmt(s['city_population_weighted_time_range'][0][j][0], 1)} to {fmt(s['city_population_weighted_time_range'][1][j][0], 1)} | {fmt(s['city_population_weighted_mean_access'][j][1], 2)} | {fmt(s['city_population_weighted_time_range'][0][j][1], 2)} to {fmt(s['city_population_weighted_time_range'][1][j][1], 2)} |\n"
    text += """\nCity means weight origins by Census population and average hourly departures.
Ranges describe these samples, not confidence intervals. Numbers are traced to
results/summary.json, oracle.json, reference_benchmark.json and deletion_timings.json.
The reference benchmark retains the latest complete run after the walking repair; benchmark.json records
the current execution, including fresh replay timings when applicable.

The [complete N-1 ranking](results/n1_ranking.csv) retains all published routes,
including inactive routes with measured zero effects. Its score is
origin-population-weighted 45-minute access lost, averaged across hourly samples.
It is scheduled dependence, not passengers, funding priority or ridership.

## Inspect and rebuild

Open [the static atlas](docs/site/index.html), the
[six-page technical note](docs/TECHNICAL_NOTE.pdf), its
[Markdown source](docs/TECHNICAL_NOTE.md) and the [proof](docs/REUSE_PROOF.md).
The page uses plain HTML/CSS and local SVGs, with no tracking or external resources.
Complete accessible CSVs accompany the charts.
Array dimensions, index maps, units and null-check meanings are in
[the output format guide](docs/OUTPUTS.md).

Requirements: Python 3.14, a C++17 compiler and requirements.lock. From a clean
checkout, run:

\x60\x60\x60sh
./rebuild.sh
\x60\x60\x60

The command installs locked packages if needed, verifies frozen hashes, prepares
inputs, recompiles routing, checks the oracle, evaluates every route deletion with
and without reuse, renders outputs and validates artifacts. Numerical rebuilding
uses no network; initial package installation may access the package registry.
Use NETWORK_LAB_PYTHON=/absolute/path/to/python for an existing locked runtime.
The option --replay recomputes every reused N-1 result and fully reruns twenty
seeded random deletions. Clean-checkout checksums and exits are in
results/replay_receipt.json. Timing receipts are new measurements and excluded
from numerical equality.

Run fixtures with python -m pytest -q. CI also runs lint, formatting, types and
frozen hash checks. Test network access is disabled; local checks do not imply
hosted CI execution.

For an offline what-if query at any service-day minute, use:

\x60\x60\x60sh
PYTHONPATH=src .venv/bin/python -m network_lab.query \\
  --origin 2021S051248110083 --departure 08:00 --remove-route 023R
\x60\x60\x60

Repeat --remove-route to combine route deletions. The command reports each
travel-time budget and whether surviving selected journeys certified reuse.
Arbitrary trip deletions use the delete_service and certificate_survives APIs;
twenty alternating-trip frequency reductions are checked in
results/frequency_checks.json and frequency_queries.csv.

## Model and limits

The compiled engine scans trips in boarding rounds without a fixed transfer
limit, respecting pickup, drop-off, prohibited transfers and minimum transfer
times. The City road graph and station pathways supply walking access, transfers
and egress. Integer seconds and a sixty-minute horizon cover all reported budgets.
Later arrival times are not estimated.

Base records store one selected optimal journey per destination, with route and
trip occurrences. A surviving certificate proves exact arrival reuse. All tied
optimal journeys are not enumerated. Affected origin/departure batches are rerouted,
which can reroute unaffected destinations within the batch. Frequency reductions
may use the rule when represented as trip deletions; retiming or additions need
a new base run.

The decomposition is signed counterfactual accounting: walking, zero-wait
shifted-trip geometry, then timetable (scheduled minus walking minus geometry).
Components add to scheduled access. Headway and span are combined because the
extension rule creates artificial all-day service for short patterns. This
calculation uses no span extension and is not causal estimation.

Road centrelines do not certify sidewalks, crossings, barriers, entrances, grade
separation, mobility access or pathway duration. Each Census area uses one
interior point; every area remains in every denominator. Connectors target the
largest road component within 300 m. If that fails, use the nearest point of the
official area polygon when its connector is within 300 m. Original-to-access
straight distance adds walking time at 1.33 m/s on access and egress; original
coordinates remain in the outputs. The build requires the exact frozen exception
set and fails on any different set. Exceptions remain in every denominator with
access computed as is. Stops without a
walking connector serve only as on-board stops. At 1.33 m/s, walking may overstate
access for older people and in winter. Integer-ceiling edge times are conservative
(about half a second per edge); omitted trails, walkways and footbridges understate
reach. The City's segment-type field marks 820 ramp and collector-distributor segments (733 of them Arterial-Class B). They are retained as walkable, which may overstate reach near interchanges.
Roads without sidewalks may overstate reach. Straight connectors ignore barriers and may overstate
reach. Library opening
hours, fares, demand, capacity, on-demand service and realised delay are outside
the primary model. Exact deletion equality does not remove these limits.

## Data, prospective protocol and release

Dated note, 2026-10-11: during a build session from 10:58 to 11:34 PT, an unscoped file search ran over the folder that contains the real-time collector; it printed no path inside the collector folder, and no collector file or payload was opened. Earlier, at about 02:10 PT, before the original registration at 02:12:15 PT, the phase 1 build read the collector's source code and listed its code files only; the collector's data and log folders are excluded from such listings by its ignore rules. At about 12:05 PT we listed the collector folder's top level (code files and the names of the data and log folders, no data file names) while checking this note. All protocol decisions, including amendment 1 (06:35 PT), were registered before these listings, except the phase 1 code read, which preceded the original registration and saw no data.

[DATA.md](DATA.md) preserves licences, source URLs and required attribution.
Frozen inputs, table counts, rejection ledgers, calendars and walking assumptions
are under data/. Code is Apache-2.0; data retain their source licences.

[PROTOCOL_REALTIME.md](PROTOCOL_REALTIME.md) pre-registers a future observed-service
comparison. Its commit, hash and time are in data/manifests/protocol_registration.json.
[PROTOCOL_AMENDMENT_1.md](PROTOCOL_AMENDMENT_1.md) freezes the decision outcomes,
coverage handling, primary latest-arrival bound and twenty-eligible-weekday
collection rule (45-day cap); its time and hash are in
data/manifests/protocol_amendment_1.json. The collector is read only.
The pilot inventory describes files and fetch logs,
with no decoded payloads or reliability claim. No publication, push or remote
repository creation is performed.

Contains information licensed under the Open Government Licence – City of Edmonton.

Adapted from Statistics Canada, 2021 Census of Population, 2021. This does not
constitute an endorsement by Statistics Canada of this product.
"""
    text = text.replace(
        "## Inspect and rebuild",
        "## City figures without moved-point origins\n\n"
        + cohort_intro
        + "\n\n"
        + cohort_markdown
        + "\n## Inspect and rebuild",
    )
    table = "\n| Route | 45-minute loss | Hourly rank range | Departures in top ten |\n| --- | ---: | --- | ---: |\n"
    table += "".join(
        f"| {r['route_id']} | {float(r['population_weighted_loss_45']):,.1f} | {r['rank_45_min']} to {r['rank_45_max']} | {r['top_ten_departures_45']}/20 |\n"
        for r in ranking[:10]
    )
    table += "\nTop ten under the 45-minute measure; hourly ties use route identifier.\n"
    for budget in (30, 60):
        table += (
            f"\n{budget}-minute top five: "
            + "; ".join(
                f"{r['route_id']} ({float(r[f'population_weighted_loss_{budget}']):,.1f})"
                for r in sensitivity["top_five"][str(budget)]
            )
            + ".\n"
        )
    table += f"\nThe prospective 0.95 rank-materiality convention requires strong agreement; the scheduled 30-versus-45-minute reference is {sensitivity['rho_30_45']:.3f} over {sensitivity['primary_routes']} routes with non-zero population loss at 30 or 45 minutes.\n"
    table += "\nThe frozen amendment's reference value 0.945433613392293 was computed over the 186 routes with a loss at any budget.\n"
    walking_table = f"\n## Walking access changes and frozen exceptions\n\n{w['moved_access_areas']} areas ({fmt(w['moved_access_population'])} residents) moved their access point. Original and moved coordinates, connector metres and added seconds are recorded in [walking_snaps.json](data/manifests/walking_snaps.json) and the model index. The frozen exception list contains {len(exceptions['areas'])} populated areas ({fmt(exception_population)} residents). The 12 moved access points are 592 m to 4,329 m from their interior points, adding 446 s to 3,256 s (about 7 to 54 minutes) of walking. Every area remains in every denominator.\n\n| Area ID | Population | Reason |\n| --- | ---: | --- |\n{exception_markdown}\n\nThe unchanged list, timestamp and SHA-256 are in [walking_exceptions.json](data/manifests/walking_exceptions.json) and [its registration](data/manifests/walking_exceptions_registration.json).\n"
    text = text.replace(
        "## Inspect and rebuild", walking_table + table + "\n## Inspect and rebuild"
    )
    (ROOT / "README.md").write_text(text)
    print("Rendered atlas, summaries, project page and technical note")


if __name__ == "__main__":
    render()
