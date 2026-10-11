"""Six-page technical note, with numerical traceability."""

import html
import re
from functools import partial

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from network_lab.common import ROOT


def fmt(x, digits=0):
    return f"{x:,.{digits}f}"


def note(s, b, o, w, g, p, ranking, amendment, sensitivity):
    exceptions = w["exceptions"]
    exception_population = sum(r["population"] for r in exceptions)
    exception_list = "; ".join(f"{r['id']} ({fmt(r['population'])})" for r in exceptions)
    exception_text = f"Frozen walking exceptions: {len(exceptions)} areas, {fmt(exception_population)} residents, retained in every denominator with access computed as is. List (ID and population): {exception_list}. Reason for every listed area: only own populated area reachable by walking in 60 minutes. List and timestamp: data/manifests/walking_exceptions.json; SHA-256: walking_exceptions_registration.json."
    upper = 100 * (1 - 0.05 ** (1 / o["reachable_queries"]))
    top_speedups = "; ".join(
        f"{r['route_id']}: {r['speedup']:.2f}x" for r in b["top_five_speedups"]
    )
    cohorts = s["origin_cohorts"]
    unchanged = cohorts["without_moved"]
    cohort_text = (
        f"The sensitivity excludes {cohorts['moved_area_count']} moved-point origins "
        f"({fmt(cohorts['moved_area_population'])} residents), leaving "
        f"{fmt(unchanged['origin_area_count'])} origins ({fmt(unchanged['origin_population'])} residents). "
        "All destinations remain in both calculations. The table gives mean reachable people "
        "/ libraries, weighted by included origin population and averaged over twenty departures."
    )
    access = [["Budget", "All origins: people / libraries", "Without moved: people / libraries"]]
    for j, t in enumerate([30, 45, 60]):
        access.append(
            [
                f"{t} minutes",
                f"{fmt(s['city_population_weighted_mean_access'][j][0], 1)} / {fmt(s['city_population_weighted_mean_access'][j][1], 2)}",
                f"{fmt(unchanged['city_population_weighted_mean_access'][j][0], 1)} / {fmt(unchanged['city_population_weighted_mean_access'][j][1], 2)}",
            ]
        )
    ranks = [["Route", "45-minute loss", "Hourly rank", "Top ten / 20"]]
    ranks += [
        [
            r["route_id"],
            fmt(float(r["population_weighted_loss_45"]), 1),
            f"{r['rank_45_min']} to {r['rank_45_max']}",
            str(r["top_ten_departures_45"]),
        ]
        for r in ranking[:10]
    ]
    other = [["Rank", "30-minute route / loss", "60-minute route / loss"]]
    for i in range(5):
        row = [str(i + 1)]
        for budget in (30, 60):
            r = sensitivity["top_five"][str(budget)][i]
            row.append(f"{r['route_id']} / {float(r[f'population_weighted_loss_{budget}']):,.1f}")
        other.append(row)
    pages = [
        (
            "1. Scope, frozen inputs and population",
            [
                "The question is how access to neighbourhood opportunities changes when scheduled service is removed. This is a supply-side opportunity measure. It includes no passenger counts, demand, vehicle capacity, fare affordability or behavioural response. The City and its transit service provide public data and no endorsement.",
                f"The frozen feed has {s['routes']} routes, {fmt(s['stops'])} stops and {fmt(g['published_trips'])} published trips. All routing records are parsed, with {g['rejected_records']} rejected records. The service day is {s['service_date']}, with {fmt(s['active_trip_occurrences'])} active trip occurrences, including adjacent service dates needed at midnight. Every declared service day is expanded; inactive published routes remain in the N-1 atlas. Counts, file hashes and versions: `data/manifests/gtfs.json` and `data/manifests/model.json`.",
                f"All {fmt(s['dissemination_areas'])} City dissemination areas are origins and population destinations, representing {fmt(s['population'])} Census residents. The official table hierarchy identifies Edmonton census-subdivision membership, and DA totals reconcile to its control total. Statistics Canada population comes directly from table 98-10-0015-01; boundaries are republished by the City. No neighbourhood total is substituted for a DA population. Membership and polygon repairs: `data/manifests/census.json`.",
                f"Each area retains its interior representative point. If it lacks a connector within 300 m, the nearest point of its official polygon is used when within 300 m of the largest road component. Original-to-access straight distance adds walking time at 1.33 m/s on access and egress. {w['moved_access_areas']} areas ({fmt(w['moved_access_population'])} residents) moved access points; original coordinates, moved points, connector metres and added seconds are in walking_snaps.json and model.json. The 12 moved access points are 592 m to 4,329 m from their interior points, adding 446 s to 3,256 s (about 7 to 54 minutes) of walking. This abstraction can alter within-area access. The {s['library_destinations']} public libraries are selected location destinations, without usage, capacity or opening-hour weights. They are not a complete inventory of public services. Input URLs, byte sizes, SHA-256 hashes, licences and verbatim attribution are in `DATA.md` and `data/manifests/sources.json`. Frozen inputs are committed for offline replay.",
            ],
            None,
        ),
        (
            "2. Routing and independent verification",
            [
                f"Integer-second travel times are evaluated at twenty hourly departures from 05:00 through 24:00, yielding {fmt(s['dissemination_areas'] * 20)} origin/departure batches. Each computes every DA and library destination. The sixty-minute horizon covers the 30-, 45- and 60-minute thresholds; later arrivals are represented by infinity and are not estimated. Full minute-grid deletion validation was projected beyond the report deadline from measured pilots. The evaluated grid and reason are in `results/design.json`.",
                "The compiled engine scans eligible trips in boarding rounds, a RAPTOR-family formulation without a fixed transfer limit. Each round reads previous earliest-ready boarding labels, scans every eligible trip, observes pickup and drop-off restrictions and relaxes walking after alighting. It continues until no alighting label improves. Scanning all trips avoids a non-overtaking assumption. Earliest readiness dominates later readiness under fixed trip times and stop-pair transfer rules. Equal labels retain a deterministic selected journey. The induction and fixed-point argument are in docs/ENGINE_PROOF.md.",
                f"The City road proxy contains {fmt(w['included_segments'])} segments. Walking uses 1.33 metres per second, integer-ceiling edge times and connectors to the largest road component within 300 metres. The City's segment-type field marks 820 ramp and collector-distributor segments (733 of them Arterial-Class B). They are retained as walkable, which may overstate reach near interchanges. Explicit station pathways supplement roads. Unknown pathway times use a documented horizontal-distance imputation. Transfer relaxation starts at the last alighting stop, so an intermediate label cannot bypass a prohibited transfer. Walking-only access is separate from transfer prohibitions. {w['unconnected_points'].get('dissemination_area', 0)} DA points lack road connectors and remain in every denominator. Records: `data/manifests/walking.json`, `walking_snaps.json` and `pathway_imputations.json`.",
                f"The independently written connection scan uses departure-ordered connections, onboard-position state and a fixed point within timestamp ties. It shares frozen parsing and walking distances, but no boarding-round algorithm or parent updates. It matched {o['matches']}/{o['queries']} random DA/departure queries, including {o['reachable_queries']} reachable cases; 0 disagreements, with a one-sided 95 percent upper bound of {upper:.2f}% over reachable queries; seed {o['seed']}. Every sampled query and both values are in `results/oracle_queries.csv`; disagreements are in `results/oracle.json`. Fixtures also use a separately enumerated journey oracle. Shared input errors remain outside this algorithmic agreement check.",
            ],
            None,
        ),
        (
            "3. Exact deletion reuse and timing",
            [
                "Fix origin, departure, destination, walking, timetable and transfer rules. Let J be feasible journeys before deletion and J_D those remaining after removing service D. Since J_D is a subset of J, the new minimum arrival cannot improve. If every optimal journey avoids D, an old optimum remains feasible, so the new minimum cannot worsen. Combining these inequalities gives equality. An unreachable query stays unreachable because deletion adds no journey. Equality concerns arrival values; the set of tied optimal journeys can shrink.",
                "The implementation uses the stronger sufficient certificate that one selected optimum survives. The base stores one deterministic optimum per destination, including trip occurrences and routes. A surviving selected journey certifies the old value even if another tied optimum used the deleted service. It does not enumerate every co-optimal journey. The pruned parent-leg graphs and destination indices are in results/optimal_witnesses.jsonl.gz; index maps are in data/manifests/model.json. Batches whose selected-route union avoids deletion are copied. All others are rerouted, including unaffected destinations within those batches. The proof and storage format are in docs/REUSE_PROOF.md.",
                f"All {s['route_deletions']} routes are deleted in a seeded random order. There are {s['full_recomputation_checks']} byte-identical full comparisons of complete destination-arrival matrices. Both raw-array SHA-256 values, affected-batch counts and wall times are in `results/deletion_timings.json`. No disagreement is replaced by an average match rate. Exactness applies to this frozen model, horizon and hourly grid.",
                f"Full deletion recomputation took {fmt(b['full_seconds'], 2)} seconds; reuse took {fmt(b['reuse_seconds'], 2)} seconds, an aggregate {fmt(b['aggregate_speedup'], 2)}x speedup, or {fmt(b['any_effect_speedup'], 2)}x over {b['any_effect_routes']} routes with any effect. Highest-loss five: {top_speedups}. The base took {fmt(b['base']['wall_seconds'], 2)} seconds. Four workers use a loaded model, including allocation and copying but excluding preparation and metric aggregation. Inactive routes and walking-only optima legitimately favour reuse; per-route timings remain available. These are workload-specific measurements. Source: `results/reference_benchmark.json` retains the latest complete run after the walking repair; `results/benchmark.json` records current execution. Frequency reduction may use the proof only as trip deletion. Retiming, new services or walking changes require a new base.",
            ],
            None,
        ),
        (
            "4. Atlas, N-1 ranking and decomposition",
            [
                "Reachable population sums residents of all DAs whose representative points can be reached within a budget, including the origin area. Library access counts reachable branch points. City means weight origins by Census population and average the twenty departures. They are mean reachable people per origin resident, not passengers or trips. Hourly ranges and DA quantiles describe modelled variation; they are not confidence intervals. Values below are from results/summary.json. Full profiles and area summaries are results/access_profiles.csv and results/access_summary.csv.",
                "A route's N-1 score is origin-population-weighted loss in 45-minute population access, averaged over the same departures. Its denominator is represented origin population times the number of departures. Route identifier breaks ties. Every published route has a result, including inactive routes with zero effects. All thresholds, library losses and every area's changes are retained in results/n1_profiles.npz and results/n1_area_summary.csv.gz. The top ten, hourly rank ranges, top-ten departure counts and budget sensitivity are on the next page, from results/n1_ranking.csv and results/ranking_sensitivity.json. High loss means scheduled network dependence under the model, not a funding priority or ridership estimate.",
                "The decomposition is signed counterfactual accounting. Walking is the baseline. Geometry adds zero-wait, freely shifted rides along published trip stop sequences and travel times. Timetable equals scheduled access minus walking minus geometry. Headway and span are combined because the extension rule creates artificial all-day service for short patterns. No span extension enters the calculation. The three components sum exactly to scheduled access; domination and additive checks are enforced. This is not causal attribution. Definitions and arrays: results/decomposition.json and results/decomposition.npz.",
                exception_text,
                cohort_text,
            ],
            [access],
        ),
        (
            "5. Route ranking and departure sensitivity",
            [
                "Top ten under the 45-minute measure. Loss is mean reachable people lost per origin resident. Each hourly rank uses all published routes, population weights and route identifiers to break equal-score ties. The range is descriptive, not a confidence interval. The top-ten count has twenty evaluated departures as its denominator. Every route and hour remains in results/route_hourly_ranks.npz.",
                f"The 30- and 60-minute top five are shown beside the 45-minute list. The scheduled 30-versus-45-minute Spearman reference is {sensitivity['rho_30_45']:.3f} over {sensitivity['primary_routes']} routes with non-zero population loss at 30 or 45 minutes. Thus the route order depends on travel-time budget. The prospective 0.95 materiality bar is a conservative operational convention requiring strong agreement, not a universal effect-size boundary.",
            ],
            [ranks, other],
        ),
        (
            "6. Replay, prospective test and limits",
            [
                "The single command ./rebuild.sh verifies frozen hashes, prepares inputs, recompiles routing, runs independent checks, computes every deletion, renders summaries and documents, and checks artifacts. It uses a locked local runtime or installs packages from the package registry. Numerical rebuilding fetches no live data. CI runs lint, types, hashes and small offline fixtures. Local checks do not imply hosted CI execution. A separate clean local clone replays every reused N-1 result and fully reruns twenty seeded deletions. Canonical numerical hashes are compared; elapsed times are fresh measurements and excluded from equality. Replay commands, exits and checksums are in results/replay_receipt.json.",
                f"The prospective real-time protocol was committed before payload analysis. Current SHA-256: `{p['sha256']}`. Commit time: {p['committed_at']}. Original registration and the pre-analysis clarification are recorded in `data/manifests/protocol_registration.json`. Amendment 1 was frozen before payload analysis: SHA-256 `{amendment['sha256']}`, registered {amendment['registered_at']}. Collect until twenty eligible weekdays, capped at 45 complete service days. Latest arrivals are primary; earliest arrivals are sensitivity. Non-zero loss on either side defines primary route correlations; all-route values are secondary. Uncovered routes or segments stay at schedule on both sides and are reported not observed. Bounded stop-event reconstruction from matched positions will compare neighbourhood and route ranks with paired whole-day bootstrap inference and an explicit decision rule. The pilot inventory reads file and fetch-log metadata only. It supports no reliability finding.",
                "Road centrelines approximate walking. At 1.33 m/s, access may be overstated for older people and in winter. Integer-ceiling edge times are conservative (about half a second per edge). Omitted trails, walkways and footbridges understate reach. Roads without sidewalks, retained ramp and collector-distributor segments and straight connectors that ignore barriers may overstate reach. Stops without a walking connector serve only as on-board stops. The build passes only when failures equal the frozen exception list exactly; any different set fails. Sidewalks, crossings, grade separation, entrances and mobility access are uncertified. Pathway duration and representative-point placement remain uncertain. Two source polygons require repair. Whole-area population at one point simplifies within-area geography. Hourly sampling can miss short headway or span changes. Fares, demand, capacity, on-demand service, opening hours and realised delay are outside the primary model. Exact deletion equality and routing agreement do not remove these input and scope limits.",
                "The release package contains raw frozen inputs, all count and rejection ledgers, route and trip journey certificates, machine-readable profiles, the full route ranking, licensing notices and a static page with accessible CSVs. Code is Apache-2.0 and data retain source licences. This public research release (2026-10-13) has no City endorsement. Preparation and local validation do not imply a public repository, push or deployment.",
                "Contains information licensed under the Open Government Licence – City of Edmonton.",
                "Adapted from Statistics Canada, 2021 Census of Population, 2021. This does not constitute an endorsement by Statistics Canada of this product.",
            ],
            None,
        ),
    ]
    body = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=9.6,
        leading=13.0,
        spaceAfter=9,
        textColor=colors.HexColor("#173342"),
    )
    heading_style = ParagraphStyle(
        "Heading", parent=body, fontName="Helvetica-Bold", fontSize=17, leading=22, spaceAfter=18
    )
    story = []
    md = [
        "# Edmonton Network Lab: technical note",
        "",
        "Scheduled access and exact service-deletion reuse",
        "",
    ]
    for i, (heading, paragraphs, tables) in enumerate(pages):
        if i:
            story.append(PageBreak())
            md.append('<div style="page-break-before: always"></div>\n')
        md.extend(["## " + heading, ""])
        story.append(Paragraph(html.escape(heading), heading_style))
        for text in paragraphs:
            md.extend([text, ""])
            markup = re.sub(
                r"\x60([^\x60]+)\x60",
                r'<font name="Courier" size="8.8">\1</font>',
                html.escape(text),
            )
            story.append(Paragraph(markup, body))
        for rows in tables or []:
            md.extend(
                [
                    "| " + " | ".join(rows[0]) + " |",
                    "| " + " | ".join(["---"] * len(rows[0])) + " |",
                ]
            )
            md.extend("| " + " | ".join(r) + " |" for r in rows[1:])
            md.append("")
            table = Table(
                rows,
                hAlign="LEFT",
                colWidths=([70, 135, 120, 130] if len(rows[0]) == 4 else [70, 190, 195]),
            )
            table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f1f0")),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.extend([table, Spacer(1, 12)])
    (ROOT / "docs/TECHNICAL_NOTE.md").write_text("\n".join(md))

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#4e6673"))
        canvas.drawString(52, 30, "TransitX Labs Inc. | Scheduled network access")
        canvas.drawRightString(A4[0] - 52, 30, str(doc.page))

    doc = SimpleDocTemplate(
        str(ROOT / "docs/TECHNICAL_NOTE.pdf"),
        pagesize=A4,
        leftMargin=52,
        rightMargin=52,
        topMargin=48,
        bottomMargin=48,
        title="Edmonton Network Lab: technical note",
        author="TransitX Labs Inc.",
    )
    doc.build(
        story, onFirstPage=footer, onLaterPages=footer, canvasmaker=partial(Canvas, invariant=1)
    )
