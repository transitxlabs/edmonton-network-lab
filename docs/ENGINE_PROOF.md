# Earliest-arrival correctness in the stated routing model

The state is earliest ready time at a boarding stop. Walking-only origin access
initialises these labels. For a transfer, walking and any minimum transfer time
are applied directly from the last alighting stop to the next boarding stop;
prohibited pairs have no such edge. Rules depend on stop pairs, not on route,
trip, fare, passenger history or vehicle capacity. Published trip times are
fixed and non-decreasing, and waiting is allowed. All physical walking costs
are nonnegative integer seconds.

The frozen-input audit in data/manifests/routing_feature_audit.json confirms
there are no frequency-table departures, route- or trip-specific transfer
rules, continuous pickup/drop-off values, booking rules or flexible location
windows requiring different routing semantics. Timed transfers are evaluated
against the fixed schedule and physical walking time, without a delay guarantee.

After round r, each boarding-ready label is the earliest feasible readiness
using at most r boardings. The base round is the complete shortest walking
closure from the origin. Inductively, the next scan examines every eligible
trip and every possible boarding stop with a previous-round ready time no
later than departure. Boarding at the first feasible occurrence is sufficient:
it reaches every later permitted alighting occurrence at the same fixed trip
arrival as any later feasible boarding on that trip. No route-level
non-overtaking assumption is used.

Every accepted alighting label extends an actual feasible prefix. Its direct
walking closure updates every reachable destination, and its transfer closure
updates every permitted next boarding stop. This proves soundness. Conversely,
the last boarding of any feasible journey extends a prefix covered by the
previous round, so its trip and alighting occurrence are scanned. This proves
completeness by induction. An earlier raw arrival at the same alighting stop
dominates a later one because all subsequent egress and stop-pair transfer costs
are fixed.

Once a full round produces no improved alighting label, the labels are a fixed
point: adding a boarding cannot improve any destination or readiness. An optimal
journey can be chosen with no repeated boarding-ready state. If it repeats a
boarding stop, its earlier readiness can wait for the later suffix and omit the
cycle. Therefore at most the number of boarding stops is needed; the final
unchanged round is included in the convergence guard. Zero-cost ties do not
require improving a label and do not break the argument.

The horizon is departure plus 3,600 seconds. Nonnegative walking and
non-decreasing trip times mean a discarded label beyond the horizon cannot
lead to an arrival back inside it. Infinity therefore means no arrival within
the horizon, not an estimate of later travel. This proof covers the fixed
routing model, not the accuracy of road centrelines or realised service.

The frozen feed's published stop times range from 15,000 to 100,440 seconds
(04:10 through 27:54), recorded in data/manifests/time_range.json. Expansion of
the previous, selected and next service dates therefore covers the evaluated
05:00 through 24:00 departures and their sixty-minute horizons. A date two days
earlier cannot reach 05:00 unless a published trip extends to at least 53:00;
the parser rejects that unsupported case instead of omitting it. A service date
two days later begins beyond the final 25:00 horizon.

The separate connection scan has a different traversal and explicit onboard
position state. Its equal-departure fixed point cannot travel backwards on a
zero-duration trip. Fixture enumeration and random real-network comparisons
check implementation agreement; they do not replace the assumptions above.
