# Edmonton Network Lab

Removing Edmonton's Capital Line LRT (route 021R) would cut the average resident's 45-minute reach by scheduled transit by 6,618 people, about 6 percent of the 111,442 they can reach today, the largest loss of any of the city's 243 published routes. The numbers come from the City's published timetable for Tuesday 2026-10-13 and 2021 Census populations for all 1,352 dissemination areas, with every route removed in turn. A TransitX Labs Inc. research release; it has no City endorsement.

![Map of Edmonton's 1,352 dissemination areas coloured by the mean number of people reachable within 45 minutes by scheduled transit, with the 22 public libraries marked.](docs/media/example-access-map.png)

Mean number of people reachable within 45 minutes from each dissemination area, averaged over hourly departures from 05:00 to 24:00 on 2026-10-13; the dots are the 22 public libraries. The [atlas](https://transitxlabs.github.io/edmonton-network-lab/) shows the same map with hourly profiles and the full route ranking (a static page, nothing to install).

## Routes whose removal costs the most access

| Rank | Route | Name | 45-minute loss (people) | Hourly rank range | Departures in the top ten |
| ---: | --- | --- | ---: | --- | ---: |
| 1 | 021R | Capital Line | 6,618.5 | 1 to 6 | 20/20 |
| 2 | 056 | Meadows - Leger - West Edmonton Mall | 3,288.0 | 1 to 8 | 20/20 |
| 3 | 009 | Southgate - Eaux Claires | 2,929.1 | 1 to 8 | 20/20 |
| 4 | 004 | Lewis Farms - University - Capilano | 2,120.3 | 2 to 13 | 19/20 |
| 5 | 114 | West Clareview - Coliseum | 1,844.7 | 3 to 28 | 14/20 |
| 6 | 107 | Belvedere - West Clareview | 1,784.6 | 3 to 22 | 16/20 |
| 7 | 119 | Eaux Claires - West Clareview | 1,626.8 | 3 to 18 | 9/20 |
| 8 | 103 | Eaux Claires - Castle Downs - Kingsway | 1,534.0 | 4 to 22 | 10/20 |
| 9 | 002 | West Edmonton Mall - Stadium - Clareview | 1,482.0 | 4 to 43 | 11/20 |
| 10 | 023R | Valley Line | 1,476.7 | 5 to 20 | 11/20 |

The loss is the origin-population-weighted mean number of people no longer reachable within 45 minutes, averaged over the 20 hourly departures. It measures how much residents' scheduled access depends on a route, not ridership or funding priority. At 30 minutes the top five are 021R (717.4), 119 (667.8), 009 (648.3), 107 (570.8) and 005 (525.0); at 60 minutes 021R (26,586.0), 056 (11,269.8), 009 (6,113.4), 004 (5,725.3) and 023R (5,394.8). All 243 routes, including those with no measured effect, are in [results/n1_ranking.csv](results/n1_ranking.csv).

## How it was checked

| Check | Result |
| --- | --- |
| Router against an independent connection scan | 2,000 random queries, 634 reachable, 0 disagreements (95% upper bound on the disagreement rate among reachable queries: 0.47%) |
| Each deletion with reuse of unchanged journeys against a full rerun | Byte-identical for all 243 routes |
| Deletion runtime, four workers | 5,320.07 s full, 821.85 s with reuse: 6.47x overall, 4.96x on the 186 routes with any effect |

| Budget | Mean reachable people per resident | Hourly range | Mean reachable libraries | Hourly range |
| --- | ---: | --- | ---: | --- |
| 30 minutes | 33,913.6 | 24,649.9 to 41,452.4 | 1.27 | 0.91 to 1.59 |
| 45 minutes | 111,442.3 | 76,192.2 to 139,424.6 | 3.81 | 2.82 to 4.70 |
| 60 minutes | 253,441.2 | 160,284.7 to 313,086.4 | 7.95 | 5.38 to 9.57 |

City means weight origins by Census population and average the hourly departures; the ranges describe those departures, not confidence intervals. Leaving out the 12 areas whose access point had to be moved (5,553 residents) changes the 45-minute mean to 111,985.6 people. Sources: results/summary.json, oracle.json, reference_benchmark.json and deletion_timings.json.

## Run it

Requirements: Python 3.14, a C++17 compiler and requirements.lock. From a clean checkout:

```sh
./rebuild.sh
```

It installs the locked packages if needed, checks the frozen input hashes, compiles the router, runs the independent check, evaluates every route deletion with and without reuse, and renders the atlas and CSVs. The numerical rebuild uses no network; the first package install may. `./rebuild.sh --replay` also recomputes every reused result and fully reruns twenty seeded random deletions (receipts in results/replay_receipt.json). Tests: `python -m pytest -q`.

A what-if query for one area, departure time and set of removed routes:

```sh
PYTHONPATH=src .venv/bin/python -m network_lab.query \
  --origin 2021S051248110083 --departure 08:00 --remove-route 023R
```

Output formats, array dimensions and units are in [docs/OUTPUTS.md](docs/OUTPUTS.md); the six-page [technical note](docs/TECHNICAL_NOTE.pdf) and the [reuse proof](docs/REUSE_PROOF.md) give the method in full.

## Method and limits

The compiled router scans trips in boarding rounds with no fixed transfer limit, respecting pickup, drop-off, prohibited transfers and minimum transfer times, on integer seconds within a 60-minute horizon. Walking access, transfers and egress use the City road network and station pathways; each Census area uses one interior point, connected to the largest road component within 300 m (or the nearest point of the area polygon). Twelve areas needed a moved access point, 592 m to 4,329 m away, adding 446 s to 3,256 s of walking; seven populated areas (2,780 residents) can reach only themselves on foot within 60 minutes and are kept as a frozen exception list. Every area stays in every denominator; the moves and exceptions are in [data/manifests/walking_snaps.json](data/manifests/walking_snaps.json) and [walking_exceptions.json](data/manifests/walking_exceptions.json).

Road centrelines do not show sidewalks, crossings, barriers or entrances, so walking reach can be overstated near arterials and interchanges and understated where trails and footbridges are missing; 1.33 m/s may overstate access for older people and in winter. Fares, demand, capacity, on-demand service, library opening hours and real delays are outside the model. Reusing a journey is exact only for the selected optimal journey; ties are not enumerated, and retimed or added trips need a new base run.

## Data and licences

[DATA.md](DATA.md) lists every source with its licence and required attribution; frozen inputs, counts and rejection ledgers are under data/. Code is Apache-2.0; data keep their source licences. A comparison with observed service is pre-registered in [PROTOCOL_REALTIME.md](PROTOCOL_REALTIME.md) and [PROTOCOL_AMENDMENT_1.md](PROTOCOL_AMENDMENT_1.md); no result from it is claimed yet. Build-session notes are in [docs/BUILD_NOTES.md](docs/BUILD_NOTES.md).

Contains information licensed under the Open Government Licence - City of Edmonton. Adapted from Statistics Canada, 2021 Census of Population, 2021. This does not constitute an endorsement by Statistics Canada of this product.
