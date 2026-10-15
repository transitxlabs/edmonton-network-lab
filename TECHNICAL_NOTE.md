# Edmonton Network Lab: technical note

Scheduled access and exact service-deletion reuse

## 1. Scope, frozen inputs and population

The question is how access to neighbourhood opportunities changes when scheduled service is removed. This is a supply-side opportunity measure. It includes no passenger counts, demand, vehicle capacity, fare affordability or behavioural response. The City and its transit service provide public data and no endorsement.

The frozen feed has 243 routes, 6,790 stops and 86,628 published trips. All routing records are parsed, with 0 rejected records. The service day is 2026-10-13, with 12,813 active trip occurrences, including adjacent service dates needed at midnight. Every declared service day is expanded; inactive published routes remain in the N-1 atlas. Counts, file hashes and versions: `data/manifests/gtfs.json` and `data/manifests/model.json`.

All 1,352 City dissemination areas are origins and population destinations, representing 1,010,899 Census residents. The official table hierarchy identifies Edmonton census-subdivision membership, and DA totals reconcile to its control total. Statistics Canada population comes directly from table 98-10-0015-01; boundaries are republished by the City. No neighbourhood total is substituted for a DA population. Membership and polygon repairs: `data/manifests/census.json`.

Each area retains its interior representative point. If it lacks a connector within 300 m, the nearest point of its official polygon is used when within 300 m of the largest road component. Original-to-access straight distance adds walking time at 1.33 m/s on access and egress. 12 areas (5,553 residents) moved access points; original coordinates, moved points, connector metres and added seconds are in walking_snaps.json and model.json. The 12 moved access points are 592 m to 4,329 m from their interior points, adding 446 s to 3,256 s (about 7 to 54 minutes) of walking. This abstraction can alter within-area access. The 22 public libraries are selected location destinations, without usage, capacity or opening-hour weights. They are not a complete inventory of public services. Input URLs, byte sizes, SHA-256 hashes, licences and verbatim attribution are in `DATA.md` and `data/manifests/sources.json`. Frozen inputs are committed for offline replay.

<div style="page-break-before: always"></div>

## 2. Routing and independent verification

Integer-second travel times are evaluated at twenty hourly departures from 05:00 through 24:00, yielding 27,040 origin/departure batches. Each computes every DA and library destination. The sixty-minute horizon covers the 30-, 45- and 60-minute thresholds; later arrivals are represented by infinity and are not estimated. Full minute-grid deletion validation was projected beyond the report deadline from measured pilots. The evaluated grid and reason are in `results/design.json`.

The compiled engine scans eligible trips in boarding rounds, a RAPTOR-family formulation without a fixed transfer limit. Each round reads previous earliest-ready boarding labels, scans every eligible trip, observes pickup and drop-off restrictions and relaxes walking after alighting. It continues until no alighting label improves. Scanning all trips avoids a non-overtaking assumption. Earliest readiness dominates later readiness under fixed trip times and stop-pair transfer rules. Equal labels retain a deterministic selected journey. The induction and fixed-point argument are in docs/ENGINE_PROOF.md.

The City road proxy contains 51,368 segments. Walking uses 1.33 metres per second, integer-ceiling edge times and connectors to the largest road component within 300 metres. The City's segment-type field marks 820 ramp and collector-distributor segments (733 of them Arterial-Class B). They are retained as walkable, which may overstate reach near interchanges. Explicit station pathways supplement roads. Unknown pathway times use a documented horizontal-distance imputation. Transfer relaxation starts at the last alighting stop, so an intermediate label cannot bypass a prohibited transfer. Walking-only access is separate from transfer prohibitions. 0 DA points lack road connectors and remain in every denominator. Records: `data/manifests/walking.json`, `walking_snaps.json` and `pathway_imputations.json`.

The independently written connection scan uses departure-ordered connections, onboard-position state and a fixed point within timestamp ties. It shares frozen parsing and walking distances, but no boarding-round algorithm or parent updates. It matched 2000/2000 random DA/departure queries, including 634 reachable cases; 0 disagreements, with a one-sided 95 percent upper bound of 0.47% over reachable queries; seed 20261011. Every sampled query and both values are in `results/oracle_queries.csv`; disagreements are in `results/oracle.json`. Fixtures also use a separately enumerated journey oracle. Shared input errors remain outside this algorithmic agreement check.

<div style="page-break-before: always"></div>

## 3. Exact deletion reuse and timing

Fix origin, departure, destination, walking, timetable and transfer rules. Let J be feasible journeys before deletion and J_D those remaining after removing service D. Since J_D is a subset of J, the new minimum arrival cannot improve. If every optimal journey avoids D, an old optimum remains feasible, so the new minimum cannot worsen. Combining these inequalities gives equality. An unreachable query stays unreachable because deletion adds no journey. Equality concerns arrival values; the set of tied optimal journeys can shrink.

The implementation uses the stronger sufficient certificate that one selected optimum survives. The base stores one deterministic optimum per destination, including trip occurrences and routes. A surviving selected journey certifies the old value even if another tied optimum used the deleted service. It does not enumerate every co-optimal journey. The pruned parent-leg graphs and destination indices are in results/optimal_witnesses.jsonl.gz; index maps are in data/manifests/model.json. Batches whose selected-route union avoids deletion are copied. All others are rerouted, including unaffected destinations within those batches. The proof and storage format are in docs/REUSE_PROOF.md.

All 243 routes are deleted in a seeded random order. There are 243 byte-identical full comparisons of complete destination-arrival matrices. Both raw-array SHA-256 values, affected-batch counts and wall times are in `results/deletion_timings.json`. No disagreement is replaced by an average match rate. Exactness applies to this frozen model, horizon and hourly grid.

Full deletion recomputation took 5,320.07 seconds; reuse took 821.85 seconds, an aggregate 6.47x speedup, or 4.96x over 186 routes with any effect. Highest-loss five: 021R: 1.12x; 056: 1.51x; 009: 1.20x; 004: 1.23x; 114: 1.76x. The base took 29.08 seconds. Four workers use a loaded model, including allocation and copying but excluding preparation and metric aggregation. Inactive routes and walking-only optima legitimately favour reuse; per-route timings remain available. These are workload-specific measurements. Source: `results/reference_benchmark.json` retains the latest complete run after the walking repair; `results/benchmark.json` records current execution. Frequency reduction may use the proof only as trip deletion. Retiming, new services or walking changes require a new base.

<div style="page-break-before: always"></div>

## 4. Atlas, N-1 ranking and decomposition

Reachable population sums residents of all DAs whose representative points can be reached within a budget, including the origin area. Library access counts reachable branch points. City means weight origins by Census population and average the twenty departures. They are mean reachable people per origin resident, not passengers or trips. Hourly ranges and DA quantiles describe modelled variation; they are not confidence intervals. Values below are from results/summary.json. Full profiles and area summaries are results/access_profiles.csv and results/access_summary.csv.

A route's N-1 score is origin-population-weighted loss in 45-minute population access, averaged over the same departures. Its denominator is represented origin population times the number of departures. Route identifier breaks ties. Every published route has a result, including inactive routes with zero effects. All thresholds, library losses and every area's changes are retained in results/n1_profiles.npz and results/n1_area_summary.csv.gz. The top ten, hourly rank ranges, top-ten departure counts and budget sensitivity are on the next page, from results/n1_ranking.csv and results/ranking_sensitivity.json. High loss means scheduled network dependence under the model, not a funding priority or ridership estimate.

The decomposition is signed counterfactual accounting. Walking is the baseline. Geometry adds zero-wait, freely shifted rides along published trip stop sequences and travel times. Timetable equals scheduled access minus walking minus geometry. Headway and span are combined because the extension rule creates artificial all-day service for short patterns. No span extension enters the calculation. The three components sum exactly to scheduled access; domination and additive checks are enforced. This is not causal attribution. Definitions and arrays: results/decomposition.json and results/decomposition.npz.

Frozen walking exceptions: 7 areas, 2,780 residents, retained in every denominator with access computed as is. List (ID and population): 2021S051248112451 (336); 2021S051248112459 (319); 2021S051248112460 (259); 2021S051248112470 (122); 2021S051248112493 (25); 2021S051248112568 (1,521); 2021S051248112577 (198). Reason for every listed area: only own populated area reachable by walking in 60 minutes. List and timestamp: data/manifests/walking_exceptions.json; SHA-256: walking_exceptions_registration.json.

The sensitivity excludes 12 moved-point origins (5,553 residents), leaving 1,340 origins (1,005,346 residents). All destinations remain in both calculations. The table gives mean reachable people / libraries, weighted by included origin population and averaged over twenty departures.

| Budget | All origins: people / libraries | Without moved: people / libraries |
| --- | --- | --- |
| 30 minutes | 33,913.6 / 1.27 | 34,081.0 / 1.27 |
| 45 minutes | 111,442.3 / 3.81 | 111,985.6 / 3.83 |
| 60 minutes | 253,441.2 / 7.95 | 254,635.5 / 7.99 |

<div style="page-break-before: always"></div>

## 5. Route ranking and departure sensitivity

Top ten under the 45-minute measure. Loss is mean reachable people lost per origin resident. Each hourly rank uses all published routes, population weights and route identifiers to break equal-score ties. The range is descriptive, not a confidence interval. The top-ten count has twenty evaluated departures as its denominator. Every route and hour remains in results/route_hourly_ranks.npz.

The 30- and 60-minute top five are shown beside the 45-minute list. The scheduled 30-versus-45-minute Spearman reference is 0.944 over 182 routes with non-zero population loss at 30 or 45 minutes. Thus the route order depends on travel-time budget. The prospective 0.95 materiality bar is a conservative operational convention requiring strong agreement, not a universal effect-size boundary.

| Route | 45-minute loss | Hourly rank | Top ten / 20 |
| --- | --- | --- | --- |
| 021R | 6,618.5 | 1 to 6 | 20 |
| 056 | 3,288.0 | 1 to 8 | 20 |
| 009 | 2,929.1 | 1 to 8 | 20 |
| 004 | 2,120.3 | 2 to 13 | 19 |
| 114 | 1,844.7 | 3 to 28 | 14 |
| 107 | 1,784.6 | 3 to 22 | 16 |
| 119 | 1,626.8 | 3 to 18 | 9 |
| 103 | 1,534.0 | 4 to 22 | 10 |
| 002 | 1,482.0 | 4 to 43 | 11 |
| 023R | 1,476.7 | 5 to 20 | 11 |

| Rank | 30-minute route / loss | 60-minute route / loss |
| --- | --- | --- |
| 1 | 021R / 717.4 | 021R / 26,586.0 |
| 2 | 119 / 667.8 | 056 / 11,269.8 |
| 3 | 009 / 648.3 | 009 / 6,113.4 |
| 4 | 107 / 570.8 | 004 / 5,725.3 |
| 5 | 005 / 525.0 | 023R / 5,394.8 |

<div style="page-break-before: always"></div>

## 6. Replay, prospective test and limits

The single command ./rebuild.sh verifies frozen hashes, prepares inputs, recompiles routing, runs independent checks, computes every deletion, renders summaries and documents, and checks artifacts. It uses a locked local runtime or installs packages from the package registry. Numerical rebuilding fetches no live data. CI runs lint, types, hashes and small offline fixtures. Local checks do not imply hosted CI execution. A separate clean local clone replays every reused N-1 result and fully reruns twenty seeded deletions. Canonical numerical hashes are compared; elapsed times are fresh measurements and excluded from equality. Replay commands, exits and checksums are in results/replay_receipt.json.

The prospective real-time protocol was committed before payload analysis. Current SHA-256: `77e8a31dc2acd2612ef824fd470bed9d6ae13a4c4d34756eb5079b5176758b2f`. Commit time: 2026-10-11T02:39:08-07:00. Original registration and the pre-analysis clarification are recorded in `data/manifests/protocol_registration.json`. Amendment 1 was frozen before payload analysis: SHA-256 `f8b0a956895fcf2a8411138419642a6f36ac0fe8300c272b1a1537e7d713064b`, registered 2026-10-11T06:35:53-07:00. Collect until twenty eligible weekdays, capped at 45 complete service days. Latest arrivals are primary; earliest arrivals are sensitivity. Non-zero loss on either side defines primary route correlations; all-route values are secondary. Uncovered routes or segments stay at schedule on both sides and are reported not observed. Bounded stop-event reconstruction from matched positions will compare neighbourhood and route ranks with paired whole-day bootstrap inference and an explicit decision rule. The pilot inventory reads file and fetch-log metadata only. It supports no reliability finding.

Road centrelines approximate walking. At 1.33 m/s, access may be overstated for older people and in winter. Integer-ceiling edge times are conservative (about half a second per edge). Omitted trails, walkways and footbridges understate reach. Roads without sidewalks, retained ramp and collector-distributor segments and straight connectors that ignore barriers may overstate reach. Stops without a walking connector serve only as on-board stops. The build passes only when failures equal the frozen exception list exactly; any different set fails. Sidewalks, crossings, grade separation, entrances and mobility access are uncertified. Pathway duration and representative-point placement remain uncertain. Two source polygons require repair. Whole-area population at one point simplifies within-area geography. Hourly sampling can miss short headway or span changes. Fares, demand, capacity, on-demand service, opening hours and realised delay are outside the primary model. Exact deletion equality and routing agreement do not remove these input and scope limits.

The release package contains raw frozen inputs, all count and rejection ledgers, route and trip journey certificates, machine-readable profiles, the full route ranking, licensing notices and a static page with accessible CSVs. Code is Apache-2.0 and data retain source licences. This public research release (2026-10-13) has no City endorsement. Preparation and local validation do not imply a public repository, push or deployment.

Contains information licensed under the Open Government Licence – City of Edmonton.

Adapted from Statistics Canada, 2021 Census of Population, 2021. This does not constitute an endorsement by Statistics Canada of this product.
