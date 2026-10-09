# State-relations engine

This adds persistent operational memory and pre-dispatch comparisons to the India
domestic workflow. Open **Optimizer > Open route memory**, or the route-memory link
on a shipment. It does not book transport or amend a shipment automatically.

## Coupled inputs

- Shipment service: cargo, delivery stops, planned times and versioned event observations.
- Document service: current authorized document metadata for compliance checks. The decision
  ledger keeps document IDs, types and verification states, not extracted PDF text/fields.
- Compliance service: current versioned rules, saved answers, per-consignment results and
  source-review freshness. New publications affect the next comparison.
- Carrier offers: administrator-reviewed all-inclusive INR quotes, vehicle dimensions,
  source references, observation/expiry dates, applicability confirmation and review rationale.
  These are manually recorded offers, not independently verified live carrier API prices.
- Optional openrouteservice HGV connector: fresh map-derived distance/driving estimates,
  payload hashes, provider warnings and 24-hour snapshot expiry. Sends only coordinates and
  vehicle restrictions to a fixed HTTPS endpoint, with explicit operator consent.

## Memory and comparison

`state_relation_records` is a profile-owned PostgreSQL ledger. HTTP workflows append offers,
event revisions, routing snapshots and decisions without overwriting prior rows. There is
no update/delete endpoint. This is application-level history, not cryptographic WORM storage.
The latest version of a carrier/reference pair is used. Every decision contains input hashes,
source references, rule versions, rejected options, scoring inputs and its previous decision ID.
Identical decisions are reused instead of appended every minute.

Whole-shipment LOADED -> ARRIVED_AT_HUB/DELIVERED pairs establish observed PIN-to-PIN
travel times. Repeated event syncs do not duplicate samples. Comparisons use the most recent
90 days, at least three observations per leg, and only if all legs have that coverage.
History is local to the signed-in profile and ships explicitly observed through this workflow;
it is neither a global logistics dataset nor a calibrated prediction model. Vehicle, load,
weather and carrier differences can make historical samples non-comparable. Historical
duration use is optional; the interface exposes sample counts and medians.

The transparent objective is:

`all-inclusive carrier price + user-selected INR/hour * conservative duration`

Duration is the maximum of quoted hours, fresh provider driving hours and optional historical
leg medians. No invented tolls, tax rates, fuel surcharges or synthetic risk probabilities are
added to an all-inclusive price. A routing estimate may lengthen the timing but never changes
a carrier's quoted price. Revised prices require new quote versions. This is a conservative
planning heuristic, not a statistically calibrated arrival-time forecast.

Offers cannot be recommended when quotes expire before booking/departure, cargo changes,
delivery stops are omitted, reviewer coverage is absent, the deadline is missed, compliance
is unresolved, routing is stale/has warnings, a linked regulation source lacks current review,
or the shipment is already moving. Demo-rule mode blocks booking recommendations entirely.
The result is the best-supported *supplied offer*, not the best route across the entire road
network, a proof of complete legal coverage, or a guarantee of carrier availability.

## Refresh and providers

The workspace syncs shipment observations and recomputes existing offers every minute while
open, with a toggle to disable it. Manual sync/compare is also available. It does not silently
call paid routing APIs on a timer: **Refresh truck route** explicitly fetches a new snapshot.
It does not poll carriers or government sites in the background when the page is closed.
Source retrieval/review remains in the Regulations workspace. Expired or changed source
snapshots require refresh/review before the associated offer can be recommended.

Optional `.env` configuration:

```env
ORS_API_KEY=your_provider_key
ALLOW_EXTERNAL_ROUTING=true
REGULATION_CATALOG_MODE=reviewed
```

Verified stop coordinates and quoted vehicle dimensions are required for routing. An India
coordinate bounding box is input validation, not point-in-country geocoding. The connector
requests HGV restrictions and avoids national borders, but map coverage may be incomplete.
The provider's road data is not a government declaration that a vehicle may legally travel.
See [provider routing options](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/routing-options).

The demo works without routing credentials using manually reviewed offers. There is no
universal free live freight-price feed configured. A contracted carrier/rate provider,
traffic/closure feeds, shipment tracking integration, coverage review and scheduled ingestion
are still needed for an unattended commercial planning service. Do not treat missing live
traffic, closures or unquoted price changes as zero-risk facts. Synthetic risk remains a
separate prototype dashboard and is deliberately not a cost adjustment here.

## APIs

- `GET /state-relations/{shipment_id}`: current profile's records and corridor observations.
- `GET /state-relations/{shipment_id}/decisions/{decision_id}`: complete saved decision inputs.
- `POST /state-relations/{shipment_id}/observe`: ingest current shipment event revisions.
- `POST /state-relations/{shipment_id}/offers`: append a reviewed carrier quote (admin).
- `POST /state-relations/{shipment_id}/offers/{offer_id}/refresh-routing`: explicit HGV refresh.
- `POST /state-relations/{shipment_id}/evaluate`: fresh deterministic comparison and history.

Rebuild: `docker compose up -d --build compliance-service web`. New tables are additive;
existing shipment, document and graph workflows are retained. Quote/decision business
metadata uses existing database/profile controls; it is not covered by document-service
field encryption. Encrypt deployment volumes/backups before storing confidential carrier terms.
