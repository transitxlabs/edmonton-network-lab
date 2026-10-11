# Prospective protocol: amendment 1

Registered at 2026-10-11T06:35:53-07:00 (America/Vancouver), before any response payload inspection,
decoding or analysis. This dated amendment supersedes the corresponding clauses
of PROTOCOL_REALTIME.md; the original protocol and registration remain unchanged.
Its SHA-256 is recorded separately in data/manifests/protocol_amendment_1.json,
so the document can be frozen without a self-referential hash.

## Decisions fixed before analysis

1. Ranking outcome: if the entire percentile 95 percent interval lies at or
   above 0.95, report no practically material ranking change. A material change
   still requires the entire interval below 0.95 and Holm-corrected rejection.
   Intervals crossing 0.95, a constant score vector, fewer than twenty eligible
   weekdays, or a below-threshold interval without corrected rejection are
   inconclusive. Apply the outcome separately to the primary area and route tests.
2. Collection: retain the start at 2026-10-11 09:08 UTC. Collect until twenty
   eligible weekdays exist, with a cap of 45 complete America/Edmonton service
   days. Apply the original holiday, matching, schedule-snapshot and 95 percent
   expected-poll rules. If the cap is reached without twenty eligible weekdays,
   report inconclusive; publish all exclusions. This registration changes no
   collector process or file. The original thirty-day endpoint is superseded.
3. Route correlations: the primary set is the union of routes with non-zero
   45-minute deletion loss on either scheduled or observed side of the paired
   window. Freeze that set for the day-bootstrap replicates. Average ranks for
   ties; routes with zero loss on both sides are excluded from the primary rank
   test. All-route correlation is a labelled secondary result. Report both
   denominators and the primary-set top-ten overlap.
4. Position coverage: routes or segments without vehicle-position coverage,
   including underground LRT where positions cannot bracket stop events, are
   held at schedule on both sides and reported as not observed. Determine
   documented coverage before decoding any response; classify undocumented
   coverage as unknown, never as confirmed observed. Retain uncovered service
   on both sides rather than dropping it from one comparator. For partially
   covered trips apply the 90 percent reconstruction rule to documented covered
   events; uncovered events stay at schedule on both sides, are excluded from
   that coverage denominator and are reported separately. Reject infeasible
   mixed timelines. Ordinary missing polls or unmatched covered trips retain
   the original exclusion rules and never imply cancellation.
5. Event bounds: the latest-arrival feasible timeline is primary. The earliest-
   arrival timeline is a labelled sensitivity, using the same paired population,
   coverage decisions, walking graph and inference procedure. Publish both.
6. Materiality: 0.95 is a conservative operational convention requiring very
   strong rank agreement, not a universal effect-size boundary; the scheduled
   30-versus-45-minute non-zero-loss reference correlation is 0.945433613392293
   at commit 5eea233, illustrating sensitivity to the travel-time budget.
   Publish the rebuilt reference beside 0.95 as well, without changing this
   threshold after observing payloads.

## Documentation check, with no payload access

The City's Real Time Trip Updates GTFS (PB File) metadata describes updates for
buses and does not establish vehicle-position coverage of LRT or tunnels:
https://data.edmonton.ca/api/views/dp5u-srkp.json (read 2026-10-11).
No affirmative LRT coverage was established from documentation in this check.
Unknown coverage must remain labelled unknown until documented; it must not be
inferred from response payloads. This amendment makes no coverage or reliability
finding from the running archive. No collector folder was accessed or changed.

Contains information licensed under the Open Government Licence – City of Edmonton.
