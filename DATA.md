# Frozen public inputs and attribution

All inputs are official public data, retrieved on 11 October 2026. Exact URLs,
retrieval times, byte sizes and SHA-256 hashes are in
`data/manifests/sources.json`. The five frozen inputs are committed for offline
replay. No account or authentication is required. Data licences are separate
from the Apache-2.0 code licence.

## Edmonton Transit Service schedule

Source: City of Edmonton, ETS GTFS schedule,
<https://gtfs.edmonton.ca/TMGTFSRealTimeWebService/GTFS/GTFS.zip>.
Feed version, complete table counts, per-file hashes, service-day expansion and
rejected routing records are in `data/manifests/gtfs.json`,
`calendar_expansion.json` and `rejected_records.json`. The zip includes regional
services as published; no route or stop sampling is applied. The selected
weekday uses its active service and the adjacent dates required at midnight.

Licence: Open Government Licence - Edmonton, version 1.0, based on the Open
Government Licence - Canada version 2.0. Terms read from the City's official
licence page: <https://data.edmonton.ca/stories/s/Open-Government-Licence-Edmonton/msh8-if28/>.
The page embeds the licence document; the extracted terms are preserved in
`data/manifests/edmonton_licence.txt`. The required attribution, word for word:

> Contains information licensed under the Open Government Licence – City of Edmonton.

The licence permits lawful copying, modification, publication, distribution and
commercial use, requires attribution and excludes third-party rights and
official symbols. It grants no endorsement and provides no warranty.

## Walking graph and public destinations

The City Road Network is `9j8t-zm52` on <https://data.edmonton.ca/>. Public libraries
are `jn25-zspi`, provided by Edmonton Public Library. Both use the City's terms
above and the same required attribution statement. Library names, coordinates
and branch identifiers are retained; opening hours do not constrain the primary
geographic-access metric. These are selected public destinations, not a complete
inventory of public services.

The Road Network supplies geometry and intersection identifiers and is usable
as a stated walking proxy. Railways and private roads are excluded. The City's segment-type field marks 820 ramp and collector-distributor segments (733 of them Arterial-Class B). They are retained as walkable, which may overstate reach near interchanges.

Dated erratum, 2026-10-11: the manifest phrase "Source fields do not identify limited access" in data/manifests/walking.json is superseded by the sentence above; a labelled sensitivity run without those segments is planned for a later version.

Points connect only to the largest road component within
300 metres. If an area's representative point has no such connector, the nearest
point of its frozen official polygon is used when within 300 metres of that
component. The straight walk from the original point to that access point at
1.33 m/s is charged on access and egress, with both coordinates retained. The
frozen exact exceptions remain in every denominator with access computed as is.
Roads and alleys are undirected, and explicit
station pathways retain their supplied direction. There is no street-data
redistribution from OpenStreetMap and no OpenStreetMap input. The historical
2016 sidewalk catalogue lacks a complete current topological pedestrian graph,
so the road source was preferred. Graph limitations and every excluded road
record, point connector and missing pathway-time imputation are recorded in
`data/manifests/walking*.json` and `pathway_imputations.json`.

## Statistics Canada boundaries and population

2021 dissemination-area boundaries are Statistics Canada data republished in
the City's `3np6-c8en` dataset, "2021 Federal Census: Edmonton Boundaries".
The boundaries were obtained from the City of Edmonton's open data portal under the City's terms.
Population comes directly from Statistics Canada table 98-10-0015-01,
"Population and dwelling counts: Canada, provinces and territories, census
subdivisions and dissemination areas", reference year 2021:
<https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810001501>.
The full official CSV and its metadata are frozen in `98100015.zip`.
The City census-subdivision identifier is `2021A00054811061`. Membership and
population reconcile to its control total; no neighbourhood total is substituted
for dissemination-area population. Two invalid source polygons are repaired
with `make_valid`, without altering membership or population; identifiers and
method are in `data/manifests/census.json`.

Licence: Statistics Canada Open Licence,
<https://www.statcan.gc.ca/en/reference/licence>. The terms were read and are
preserved in `data/manifests/statcan_licence.txt`. The required notice templates,
word for word, are:

> Source: Statistics Canada, name of product, reference date. Reproduced and distributed on an "as is" basis with the permission of Statistics Canada.

> Adapted from Statistics Canada, name of product, reference date. This does not constitute an endorsement by Statistics Canada of this product.

Applied to the reproduced population input:

> Source: Statistics Canada, Population and dwelling counts: Canada, provinces and territories, census subdivisions and dissemination areas, 2021. Reproduced and distributed on an "as is" basis with the permission of Statistics Canada.

Applied to the reproduced boundary input:

> Source: Statistics Canada, 2021 Census of Population dissemination area boundaries, 2021. Reproduced and distributed on an "as is" basis with the permission of Statistics Canada.

Applied to the derived atlas and project page:

> Adapted from Statistics Canada, 2021 Census of Population, 2021. This does not constitute an endorsement by Statistics Canada of this product.

The licence permits reproduction and value-added products with accurate source
identification and forbids suggesting endorsement or attempting to identify
individuals. Source data are provided as is.

## Real-time pilot archive

Only file names, compressed byte counts, compressed-file hashes and fetch-log
metadata are inspected. No response payload is decoded or analysed in this
release. The collector is read only and continues independently. The prospective
protocol is committed before this inventory. The pilot manifest lists the
official feed URLs and uses the Open Government Licence - Edmonton and its
required attribution above. The committed protocol's hash and time are in
`data/manifests/protocol_registration.json`. Collection gaps describe archive
coverage and support no service-reliability claim.
