# Output formats and index maps

`data/manifests/model.json` is the common index map. Stops precede DA points,
which precede library points. `routes` gives the published route order and
`trip_ids` gives service-date/trip occurrence identifiers. DA and library
identifiers, coordinates, populations and DA geometries are retained in `points`.
`results/design.json` defines the evaluated departure seconds and thresholds.
The arrays use integer seconds and integer population or destination counts;
summary means and population-weighted scores are floating-point arithmetic.

DA coordinates remain the original representative points. Each DA's `access_point`
records the fallback point, movement flag, straight-line metres, connector metres
and integer-ceiling added walking seconds. Those seconds are included in the
walking graph on access and egress, so boarding eligibility, scheduled arrivals,
walking-only reach, geometry references and deletion checks use the original point.
`walking_snaps.json` retains both points and the same connector ledger.
`walking_exceptions.json` and its separate registration freeze the exact allowed
failure set before rebuilding; populations and reasons must also match.

`summary.json` contains `origin_cohorts`: all origins and the sensitivity excluding
moved-point origins, with each cohort's count, population, weighted mean access
and hourly range. Every destination and its population remain in both calculations.
Only origin membership and its population-weight denominator change.

## Base access and journey certificates

`base_results.npz` contains `arrivals` and `route_support`. Arrival rows are
origin-major, then departure-major. Columns are every DA followed by every
library in the model map. Values are absolute seconds relative to the selected
service-day midnight. The value 1,000,000,000 means no arrival within the
sixty-minute horizon, not an estimate of later arrival. `route_support` has the
same rows and one column per published route: a value of one means that at
least one selected destination journey uses that route.

`optimal_witnesses.jsonl.gz` has one JSON record per origin/departure row.
`destination_leg` selects the final transit leg for each destination. Legs are
six integers: parent leg, trip occurrence, boarding stop, alighting stop,
boarding second and alighting second. Parent indices always precede children.
A negative final-leg index is walking-only or unreachable, distinguished by the
arrival value. Walking access, transfers and egress are governed by the frozen
model; legs record the transit part of a selected optimum. All tied optima are
not enumerated. The route footprint is the union over these selected journeys.

`access_profiles.npz`, key `values`, has dimensions origin/departure row,
threshold and destination kind. Threshold order is 30, 45, 60 minutes; kind
order is population, libraries. `access_profiles.csv` names every column and
retains origin identifiers, departure seconds and origin populations.
`access_summary.csv` gives each DA's mean, minimum and maximum over evaluated
departures, separately by threshold and kind. `spatial_quantiles.json` contains
DA quantiles of these hourly means, without origin-population weighting.
`map_legend.json` records the quintile breaks used in the map. These ranges
and quantiles describe the frozen model; they are not confidence intervals.

## Service deletions

`n1_profiles.npz`, key `values`, adds an initial published-route dimension to
the access array. It stores base access minus reduced-schedule access, so values
are nonnegative losses. It includes every route, DA, departure, threshold and
kind. `n1_area_summary.csv.gz` averages these losses over departures for each
route and DA. No DA population weight is applied within an individual DA row.

`n1_ranking.csv` applies origin-population weights and averages departures.
Population-loss columns are mean reachable people lost per origin resident;
library-loss columns are mean reachable library locations lost. Destination
populations are already summed in the access values. Rank uses the 45-minute
population score, descending, with route identifier as the tie breaker. It is
not a demand or passenger ranking. Published inactive routes remain present.

`deletion_timings.json` has one record per route, in seeded test order. It
records affected batches, result SHA-256 values and both wall times. Full-run
records have `byte_equal: true`; replay fully compares twenty seeded routes,
while other replay records have a null full hash and check status. A null value
never means a completed full comparison. `benchmark.json` describes the current
execution. `reference_benchmark.json` preserves the latest complete benchmark after the walking repair
used in the release documents. Runtime excludes input preparation and access
metric aggregation, and includes routing allocation and result copying.

`frequency_checks.json` specifies twenty seeded alternating-trip reductions,
the exact deleted occurrence indices, reduced-model hashes and comparison
counts. `frequency_queries.csv` records full, reused and independent arrival
hashes for each diagnostic origin/minute batch. Other service dates and all
walking and transfer rules stay fixed. This is a correctness exercise, not an
estimate of a representative frequency policy's impact.

## Decomposition and validation

`decomposition.npz`, key `values`, adds a final three-component dimension to the
access array: walking, geometry and timetable. Geometry is the gain from
zero-wait shifted rides. Timetable is scheduled access minus walking minus
geometry, a signed loss relative to that ideal. Their sum equals scheduled
access exactly. Definitions are in `decomposition.json`. Headway and span are
combined because the extension rule creates artificial all-day service for
short patterns; no extension is used. The old span_extension.json manifest is
historical evidence only. This is counterfactual accounting, not causal attribution.
`decomposition_area_summary.csv` gives each area's hourly-mean components and
scheduled access for every threshold and destination kind, in named columns.

`oracle_queries.csv` records seeded DA/destination/minute checks and both arrival
values. `oracle.json` records its denominator, reachable count and disagreement
ledger. `numerical_checksums.json` hashes canonical compressed files, raw base
values, route footprints and the compiled input model. Elapsed times are
excluded. `artifact_checks.json` records coverage, monotonicity, certificate,
local-page and document checks. `replay_receipt.json` records a separate clean
local checkout, its command, exits and comparisons with the canonical hashes.

The pre-registration and pilot collection inventory are frozen evidence rather
than outputs regenerated by numerical rebuilding. Their hashes and times are
in `data/manifests/protocol_registration.json`; file and fetch-log metadata are
in `pilot_archive.json` and `pilot_fetch_log.tsv`. No response payload is decoded.

`route_hourly_ranks.npz` contains `ranks` and population-weighted `scores` with
published-route by departure dimensions under the 45-minute measure. Identifier
breaks ties. n1_ranking.csv gives each route's minimum/maximum hourly rank and
number of top-ten departures. ranking_sensitivity.json records the 30-, 45- and
60-minute top five and budget-reference correlations over routes with any effect.
PROTOCOL_AMENDMENT_1.md and its separate hash/time manifest are frozen evidence.
