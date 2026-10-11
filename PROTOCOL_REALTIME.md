# Scheduled and observed access: prospective protocol

Status: pre-registered before inspection or analysis of response payloads.
The archive is a pilot until thirty complete local service days are available.
No reliability finding is claimed by this protocol or the pilot manifest.

## Question and analysis population

Does accessibility reconstructed from observed vehicle positions change the
ranking of Edmonton dissemination areas or routes relative to the frozen
schedule? The primary population is the same 2021 City of Edmonton dissemination
areas and routes used by the scheduled atlas. Keep the walking graph, population,
destinations, departure grid and sixty-minute journey horizon fixed. Archive
files are not decoded before this document is committed and its hash and commit
time recorded. File names, byte sizes, fetch logs and compressed-file hashes may
be inspected solely to describe collection coverage.

The prospective window starts at 2026-10-11 09:08 UTC and ends after thirty
complete America/Edmonton service days. Freeze schedule snapshots throughout
collection; use the snapshot applicable to each day. If a corresponding schedule
is absent, exclude the day with an explicit reason. Analyse weekdays separately
from weekends and holidays. Release all exclusions and coverage denominators.

## Reconstruction, frozen before analysis

Match each vehicle's trip identifier, route, direction and start date to the
applicable schedule. Reject unidentified or conflicting assignments. Deduplicate
by vehicle, timestamp and trip. Reject reversed timestamps, locations outside
the network bounding box, implied speeds above 130 kilometres per hour and
ambiguous branches. Map-match sequences to the scheduled shape with monotone
distance along the shape, allowing only a stated 100 metre lateral tolerance.
Infer each stop passage by interpolating along-shape distance between two
positions that bracket the stop, no more than ninety seconds apart. Require
positions before and after the passage, within 150 metres along-shape distance.
Use intervals, bounded by the timestamps of those positions, rather than
claiming an observed dwell or door-opening time. Infer arrival and departure
intervals independently where a vehicle remains within thirty metres of a stop;
otherwise use the same passage interval and flag it. A passage is not proof
that a passenger could board. Evaluate both passage-as-service and the subset
corroborated by trip updates, reporting them separately. Trip updates are
corroboration, never substituted for observed positions in the primary result.

Never treat a missing vehicle, missing poll or unmatched trip as a cancellation.
Primary paired analysis uses matched trips with at least 90 percent of stop
events reconstructed and days with at least 95 percent successful expected
vehicle-position polls. Report excluded service by route and time. Compare the
same matched service subset on the schedule side. A secondary network analysis
may impute the schedule for unknown events, explicitly labelled imputed. Bound
earliest and latest access by the reconstructed event intervals. If their
ordering violates a feasible trip timeline, exclude the trip and record why.

## Metrics and inference

Primary neighbourhood metric: origin-population-weighted, departure-averaged
reachable population within 45 minutes. Rank areas by their own departure mean;
compare scheduled and observed ranks with Spearman correlation and population-
weighted absolute percentile-rank displacement. Primary route metric: the
population-weighted loss of 45-minute access when that route is deleted, with
the same matched service and walking model. Compare route ranks by Spearman
correlation and top-ten overlap. Secondary thresholds are 30 and 60 minutes;
report these descriptively without additional significance claims.

Use paired whole-day bootstrap resampling (10,000 replicates, seed 20261011),
stratified by weekday, preserving all areas and routes together within each day.
Report percentile 95 percent intervals for rank correlations, displacement and
top-ten overlap. A paired day-level sign-flip randomisation test (100,000 draws,
same seed) tests whether mean signed area access differences equal zero, with
the citywide population-weighted difference as the statistic. Test route and
area rank change against correlations of at least 0.95 using the bootstrap
upper bound. Recompute monthly mean scores and ranks within every day-bootstrap
replicate, using average ranks for ties. For each rank correlation, compute the
one-sided, null-centred bootstrap p value as
`(1 + count(rho_boot - rho_observed <= rho_observed - 0.95)) / 10001`.
This is a block-bootstrap approximation, not a finite-sample exact test. A
constant score vector produces an inconclusive rank decision. Apply Holm
correction to these two p values at family alpha 0.05. Declare a practically
material ranking change only if the corrected
test rejects and the entire 95 percent interval lies below 0.95. If fewer than
twenty eligible weekdays remain, or bounds cross the decision threshold,
report inconclusive. Day resampling supports only this window, not seasonal
generalisation. Spatial units are not independent experimental replicates.

## Audit and limits

Publish reconstruction software, version, frozen input hashes, event intervals,
missingness by route and day, exclusions, both scheduled comparators and all
metric denominators. Do not disclose persistent vehicle identifiers in the
project page. Vehicle-position sampling, selection from matching, map-matching,
unobserved door operation and missing trips can bias the result. This is an
access comparison, not ridership, demand, causality or reliability estimation.
Any change to this protocol must be a dated amendment made before the relevant
analysis and reported separately from the primary analysis.
