# India freight route intelligence

The commercial **Optimizer** now contains a state-wise road-freight comparison workspace.
Select a consignment, confirm the pickup/drop loading gates in existing freight planning,
then choose the assigned truck profile or enter a hypothetical truck's dimensions, tare,
and maximum actual axle load. Choose priorities, departure and planned stops, and run
**Compare freight routes**. Saved studies belong to the requesting organization and
require the existing trade planning/read grants.

## Inputs and dynamic sources

| Input | Source and use | Limit |
|---|---|---|
| Road alternatives | ORS `driving-hgv` / OpenStreetMap: fastest, shortest, avoid mapped tollways; an additional detour around reviewed public blocking polygons when applicable | Real geometries are deduplicated; fewer alternatives are possible. HGV map restrictions are not government certification or live traffic. |
| Truck feasibility | Actual assigned profile or explicit dimensions; kilograms converted to ORS tonnes, millimetres to metres | Hypothetical trucks inherit no vehicle-bound permits. Retained topology restrictions are checked separately. |
| State corridor | Polygon intersections along the whole returned road shape, preserving re-entry | Default geoBoundaries ADM1 reference exposes its represented year and attribution. It is a third-party reference, not authoritative boundary clearance. Unknown/ambiguous intervals remain unknown. |
| Transit applicability | Existing published compliance packs, exact nominated-vehicle permit evidence, reviewed corridor policies/events | Domestic GST/e-way-bill and permit requirements are distinct from international customs. Unpublished/unsupported rules are not invented. |
| Official source currency | Bounded fresh retrieval of registered HTTPS `gov.in`/`nic.in` sources, compared to their captured byte hashes | Changed, unavailable or unqueried sources require review; unchanged bytes do not establish that every applicable law has been found. Six distinct sources per study are checked; remaining sources are explicitly unqueried. |
| Weather | Open-Meteo precipitation, gusts and visibility at seven route/time samples per alternative | Forecast interpolation and the displayed exposure index are application heuristics, not official warnings, incident probabilities or continuous monitoring. Out-of-window/null/failed forecasts are unknown. |
| Corridor memory | Actual departure/arrival events matched to accepted route plans, within current organization/trade read grants, execution mode and last 90 days | Exact directed state sequences, including re-entry; at least three journeys before scoring median excess time. Most recent 200 permitted route plans are considered. Driver reports are not verified GPS or measured border dwell. |

Road class/toll exposure comes from the returned ORS extras. Major-road classification
means the provider's motorway/trunk/primary grouping; it does not certify that a road
is a particular Indian National Highway. Traffic, crime/security, pavement condition,
unmapped height/weight limits and unconfigured incident feeds remain unverified.

## Comparison and explanation

The deterministic engine first excludes candidates with a proven retained truck
restriction failure, a reviewed blocking corridor impact, an uncovered nominated permit
state, an expiring permit, or a contradictory state pin. Other evidence gaps remain
visible conditions. The remaining routes are compared using user-selected distance,
mapped travel time, road/weather exposure, directed corridor history and mapped
toll-road exposure weights. A factor is scored only if **every eligible alternative**
has that observation; omitted factors are listed and their weights redistributed
identically. Weighted min-max loss uses exact fractions and a deterministic tie break.

Mapped travel time is driving time plus declared stops; it is distinct from an arrival
estimate adjusted by reviewed delays. Unknown additional delay is not a zero-delay ETA.
Historical excess time is shown separately and is not counted twice. The result shows
overlaid route geometry and reference state outlines, a ranked comparison table,
distance/time differences, factor contributions, Pareto alternatives, state transit
evidence, sources and unresolved checks. A single returned candidate is explicitly
identified as insufficient evidence of superiority over other roads.

“Preferred” means best **among these returned alternatives under the selected weights**.
It is not proof of a global optimum or a guaranteed safe/legally cleared journey.
There is no invented interstate political-relationship score. State-to-state operational
experience is represented by the scoped observed history and actual reviewed restrictions.

Optional API fuel assumptions produce a separately labelled fuel-only estimate; toll
kilometres do not imply toll rupees. Carrier offers, accepted prices, bookings, route
commitments, authorizations and pickup/departure gates retain their existing workflows.
The feature does not automatically book, dispatch, reroute or reprice a shipment.

## Configuration

Set server-only variables in the repository-root `.env` (names are in `.env.example`):

```dotenv
ORS_API_KEY=<your ORS key>
ALLOW_EXTERNAL_ROUTING=true
ORS_DIRECTIONS_URL=https://api.heigit.org/openrouteservice/v2/directions/driving-hgv/json
FREIGHT_WEATHER_PLAN=NON_COMMERCIAL
OPEN_METEO_API_KEY=
FREIGHT_STATE_BOUNDARIES_FILE=
```

For commercial weather use, select `FREIGHT_WEATHER_PLAN=COMMERCIAL` and supply the
customer Open-Meteo key; `DISABLED` leaves weather unknown. A configured boundary file
must be accessible to the document worker, be a bounded GeoJSON FeatureCollection of
valid state polygons, and include `properties.state_code` (GST codes). Supply top-level
`year` and `attribution`; the UI continues to identify it as a reference requiring review.
Blank uses the attributed public geoBoundaries reference (currently represented year
2011, despite newer retrieval/build dates). Provider keys are never returned to the UI,
written into studies, included in evidence exports or sent with documents.

Both Shipment Service and the existing document worker consume the root environment.
Recreate/rebuild those services after deployment as appropriate to their Docker mounts.
Run the normal versioned migrations; `trade_010` adds one study table and immutable
terminal-history triggers. It does not modify commercial tables or existing data.

## Durability, freshness and privacy

The existing outbox/leased worker captures inputs, fetches external data outside database
transactions/locks, then rechecks authority and factual dependencies before publishing.
Concurrent claims cannot publish twice. Permission loss prevents publication. A change
to cargo, gates, truck, permits, published rule/event context or scoped observations makes
the stored study historical. Recommendations expire after at most 15 minutes and are
rechecked at read time. The UI polls in-progress studies and hides recommendations after
failed refreshes; no live failure is replaced by a retained or demo route.

Retained topology is a separate explicit source choice, labelled schematic when road
geometry is absent. Source export permissions are enforced. Raw input witnesses, documents,
full source/evaluation hashes, private event details and freight prices are not exported
through the public study view. External providers receive only necessary pins/truck inputs,
sampled weather coordinates, and already-public reviewed closure geometry. Saved results
remain within the existing authenticated database, retention, backup and access controls.

## API and validation

- `GET /api/v1/consignments/{id}/freight-route-intelligence`
- `POST /api/v1/consignments/{id}/freight-route-studies` (202, existing idempotency transaction)
- `GET /api/v1/freight-route-studies/{id}`
- `GET /api/v1/freight-route-studies/{id}/evidence-manifest` (permission-filtered result)

Generated OpenAPI/schema/Postman templates are part of the existing freight contract
exporter. Backend tests cover provider units/deduplication/outages, safe redirects,
boundaries/re-entry, missing forecasts, weighting/exclusions, history, permits/expiry,
worker races, revocation, stale results, immutability and tenant isolation. The existing
authenticated freight browser acceptance now exercises retained route studies at desktop
and mobile widths before its original commercial commitment assertions.

An opt-in live check uses public synthetic Bengaluru–Chennai gates and no shipment data:

```powershell
.venv\Scripts\python.exe scripts/freight-routes-live-check.py --live
```

It uses configured API allowance and writes a sanitized report to
`artifacts/audit/freight-routes/live-check.json`. It does not start application services.

Primary provider references: [ORS HGV options](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/routing-options),
[ORS extras](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/extra-info/),
[Open-Meteo](https://open-meteo.com/en/docs),
[geoBoundaries India metadata](https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/),
[E-way Bill FAQ](https://docs.ewaybillgst.gov.in/html/faq1.html).
