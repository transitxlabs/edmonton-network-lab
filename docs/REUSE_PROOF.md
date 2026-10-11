# Service deletion and exact reuse

## Query and feasible set

A query fixes an origin point, departure second, destination point and the
walking, schedule and transfer rules. Its objective is earliest arrival, capped
at departure plus 3,600 seconds. The value is infinity when no journey arrives
within that horizon. Finite values are integer seconds. The engine batches all
destinations for one origin and departure; the objective remains separate for
each destination.

Let `J` be the original feasible journeys and `J_D` those remaining when service
set `D` is deleted. Only deletion is permitted: walking edges, trip times,
transfer rules and objective do not change. Then `J_D` is a subset of `J`, so
`min cost(J_D) >= min cost(J)`.

## Requested rule

If every optimal journey in `J` avoids `D`, each stays feasible in `J_D` and
retains its original arrival. At least one such journey attains the old minimum,
so `min cost(J_D) <= min cost(J)`. Combining both inequalities gives equality.
An originally unreachable query remains unreachable because deletion cannot
add a feasible journey. Ties, walking-only optima and inactive services are
covered. This is a statement about arrival values, not preservation of the
complete set of optimal journeys, which can shrink after deletion.

## Stronger sufficient certificate used by the implementation

The same proof needs only one surviving optimum. For each destination the base
run stores one deterministic selected optimal journey, including its trip
occurrences and route identifiers. If that certificate avoids `D`, its value
can be reused even when another tied optimum used `D`. This condition includes
every query covered by the requested rule and can reuse additional tied cases.
The implementation does not claim to enumerate every co-optimal journey.

`results/optimal_witnesses.jsonl.gz` records, per origin/departure batch, a
pruned parent-leg graph and the selected leg for every destination. Each leg
contains parent index, trip occurrence index, boarding stop, alighting stop,
boarding second and alighting second. The trip-to-route and index maps are in
`data/manifests/model.json`. A negative destination-leg index denotes a
walking-only or unreachable value, distinguished by the base arrival array.
The union of selected journey routes forms the conservative batch footprint.

After deleting a route, batches whose footprint omits it are copied unchanged.
Every other batch is rerouted on the reduced schedule. Rerouting can include
unaffected destinations within an affected batch; this is a batching cost,
not an approximation. For trip deletion the same certificate rule applies to
the stored trip identifiers; the engine accepts a removed trip occurrence.
Frequency reduction must be represented as actual trip deletions to use this
rule. Arbitrary delays, retiming, route additions or walking changes require
a new base calculation.

## Verification boundary

The final experiment deletes every published route, compares reused and full
destination-arrival arrays byte for byte, and saves both SHA-256 values and
timings in `results/deletion_timings.json`. Route order is a seeded random
permutation. At least twenty independently selected routes are fully recomputed
again in clean-checkout replay. The independent connection scan tests arrival
values on 2,000 random origin/destination/minute queries.

These checks establish deletion equality for this frozen model and hourly
grid. They do not make the road proxy exact to actual pedestrian conditions,
prove real-time reliability or imply that schedule times are realised. The
theorem is general under its assumptions; empirical match rates have only the
reported finite denominators.
