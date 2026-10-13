# Phase 5: Freight Planning and Commitment

## Scope

Pre-pickup Indian interstate ROAD goods movement, one pickup, one delivery,
one vehicle, one driver, INR and a single freight payer established by the
accepted commercial revision. Existing manual movement and dispatch flows remain.
The result is decision support among submitted candidates, not a claim about
India's cheapest route, legal clearance, guaranteed arrival or disruption probability.

## Start and Navigate

From the repository root, after pulling changes:

```powershell
docker compose up -d --build shipment-service document-worker web
```

The default website is `http://localhost:3000`. Compose startup migrates the
shipment database to `trade_005`. Keep the existing database volumes and document
keyring; never use `down -v` or replace encryption keys to apply this upgrade.
The durable document worker also performs route-generation and TradeTwin jobs.

Open Trades, an accepted trade, Operations, then Optimizer. Shipments exposes the
committed plan; Risk shows exclusions; Graph shows decision relationships;
Evidence exports a permission-filtered replay; Regulations manages retained data.
Carrier dispatchers use Transport tasks -> Carrier freight offers
(`/optimizer/freight`). Assigned drivers see only their committed operational route.
No ninth top-level module is introduced.

## Roles

Organisation owners must grant capabilities through the existing membership
workflow. An interface-role choice never grants authority.

| Capability | Purpose |
| --- | --- |
| `TRADE_PLANNER` | Pins, route generation, RFQs, runs and selection proposals |
| `TRANSPORT_PLAN_APPROVER` | Apply the coordinating organisation's plan |
| `FREIGHT_COST_PREPARER` | Prepare the payer's private cost assumptions |
| `FREIGHT_PROCUREMENT_APPROVER` | Review costs and approve the payer's expense |
| `CARRIER_DISPATCHER` | Own fleet/profile, invited offers, explicit acceptance |
| `CARRIER_EVIDENCE_REVIEWER` | Independent own-carrier transport evidence review |
| `ROUTING_DATA_PREPARER` | Prepare retained route data and its planning policy |
| `ROUTING_DATA_STEWARD` | Independently review, publish and suspend datasets |
| `INTEGRATION_ADMINISTRATOR` | Inspect approved routing-provider capabilities |

Payer, coordinator and carrier decisions bind exact proposal/quote hashes. A
coordinator cannot approve another organisation's expense. Where payer and
coordinator are the same organisation, the approving actor needs both capabilities.
Carrier dispatchers see their own fixed offer, not competitors or private payer
estimates. Drivers cannot access bids, comparisons or financial source documents.

## Production Workflow

1. Accept the Phase 1 agreement. Shared/unresolved freight responsibility needs an
   accepted amendment before planning; a pending amendment is not an accepted fact.
2. Allocate the Phase 2 consignment with actual cargo measurements. Confirm pickup
   and drop pins against the accepted addresses. An area centroid is not a loading gate.
3. Have a carrier declare an immutable routing profile: overall dimensions,
   combined tare, authorised combined weight and independently declared actual
   axle load. Cargo weight is added to combined tare once, never inferred per axle.
4. Independently review and publish a licensed retained road dataset with exact
   access nodes, connected edges, ordered state transitions, measured restrictions,
   coverage, provenance and a versioned baseline planning policy.
5. Generate bounded retained alternatives. Unknown restrictions or intermediate
   states remain unknown. There is no centroid, passenger-car or straight-line fallback.
6. Publish an RFQ with routes, windows, service requirements and invited carriers.
   The published request is immutable. Additions to invitations are separate records.
7. Carriers prepare immutable fixed-price revisions. Enter integer paise charges,
   discounts, explicit carrier tax, service coverage and optional gross waiting terms.
   Reviewed `FREIGHT_QUOTE` documents may be referenced only after the existing
   document desk's effective review. Reviewing a PDF alone submits no commercial offer.
8. Submit offers. No resources are reserved. Indicative or incomplete offers cannot
   be committed. Expiration is computed from trusted time, including the exact boundary.
9. If needed, the payer declares private external costs and recipient-tax cash
   estimates. Unknown required costs leave a partial subtotal, not a cheapest label.
   Included categories cannot be added externally. Independent payer review is required.
10. Run TradeTwin. Inputs, regulatory references, sources, as-of time and engine
    version are frozen. Existing durable jobs compute cost/time/balanced rankings,
    exclusions, Pareto membership, calculation steps and remaining release work.
    Graph opens with a compact decision overview; candidate inspection and the
    all-relationships view retain full constraints and source references.
11. Use what-if waits/stops at origin, transit or destination. Origin delay shifts
    departure and arrival; unloading delay shifts completion only. Stress scenarios
    never become commitments; revise the BASE intent for a real operational change.
12. Propose a rankable BASE candidate, obtain payer/coordinator approval, then have
    the carrier explicitly accept the exact offer and nominated assignment.
13. The existing Phase 2 transaction rechecks activity, membership, capacity and
    overlap, replaces a permitted pre-pickup assignment atomically, reserves resources
    and records immutable freight commitment/route-plan revisions. It changes the
    Phase 4 factual context once. Goods prices and payment allocations remain unchanged.
14. Prepare/review actual assignment-bound Phase 4 evidence and facts. Obtain a new
    evaluation, packet, review and action-bound authorisation before pickup/departure.
    A candidate assessment or commitment is not a dispatch authorisation. Dataset
    suspension, changed profile/pins and changed assignments invalidate release dependencies.

Cancellation is bilateral, with distinct coordinator approval where applicable.
It records the agreed fee position and releases resources, not a carrier payment or
refund. Independent consignment cancellation preserves freight service history and
leaves unresolved financial obligations explicit.

## Exact Calculation and Replay

Money is integer paise. External rates and quantities use Decimal, rounded HALF_UP
once per component. Balanced normalisation uses exact fractions with stable ties;
weights cannot waive hard blockers. Cost, arrival, completion, constraint coverage,
planning outcome, comparison completeness and dispatch readiness are separate states.
Resource availability at evaluation is not a reservation. Hashes establish integrity,
not truth, issuer authority or legal clearance.

The replay retains dataset/template/profile/location/quote revisions, regulatory
references, exact scenario inputs and calculation facets. Exports enforce source
licensing and financial permissions. Masked responses omit costs, ranks, Pareto
ordering and savings. Other-trade resource conflicts expose no other trade identity.

## Deterministic Demonstration

The fixture is deliberately SIMULATION: Karnataka `29` -> Tamil Nadu `33`,
100 cartons, 400 kg, 3.5 m3, synthetic gates and measurements. The detour's `28`
is an artificial historical fixture label, not a current production GST state code.

| Offer | Quoted payable | Driving + planned stop | Outcome |
| --- | --- | --- | --- |
| A | INR 18,900 | 6 h + 30 min | Lowest comparable cost; Pareto |
| B | INR 22,050 | 5 h + 30 min | Earliest arrival; Pareto |
| C | INR 16,800 | 8 h + 30 min | Intermediate-state permit/scope gap; unranked |
| D | Known partial amount | Same retained direct route | Required loading cost unknown; unranked |

B's eligible earlier-arrival comparison costs INR 3,150 more than A. A has 30
free waiting minutes, 15-minute increments and INR 250 gross per increment;
46 minutes costs exactly INR 500. This is a declared stress scenario, not a prediction.

For a fully isolated, authenticated browser demonstration:

```powershell
cd apps/web
npm run build
cd ../..
.venv/Scripts/python.exe scripts/freight-browser-check.py
```

It creates disposable local profiles/databases, exercises independent roles on
port 3145, records screenshots in `artifacts/audit/freight`, verifies the fresh
release handoff, then stops its servers. Windows process-tree cleanup may require
running this check from a terminal permitted to stop its own subprocesses.
If Postman CLI is installed, it also performs local synthetic privacy assertions
with reporting disabled. Temporary session credentials never enter shared artifacts.
The ordinary navigation-bar demo remains unchanged; it is not the Phase 5 fixture.

For a CLI fixture on a dedicated disposable shipment database, run from
`services/shipment-service`:

```powershell
../../.venv/Scripts/python.exe -m app.freight.cli --namespace phase5-demo-001
```

Use a new namespace/database for another allocation; seeding is not a reset or
idempotent replay of an already allocated fixture. Seeded users are test identities,
not OAuth impersonation of real users. Do not run the fixture against real profiles
or label synthetic source records as production evidence.

## API and CI Artifacts

`docs/postman/freight-planning.openapi.json`, ten versioned command schemas,
`freight-planning.collection.json` and `freight-planning.environment.json` are
generated by `scripts/export-freight-contracts.py`. Credential placeholders are blank.
RFQ publication uses `request_hash`; submission/withdrawal use `quote_hash`;
decisions use `proposal_hash` and `quote_hash`. Legacy `content_hash` command
aliases remain accepted for these exact-hash operations.

Every mutation requires `Idempotency-Key`. Mutable heads also require their
current `If-Match`; a run request binds the compliance-context ETag. Replays
recheck membership/capability revocation. Current-head pointers are typed UUID
foreign keys, including circular quote/selection pointers with named constraints.
`GET /freight-quotes/{head_id}` returns history; revision IDs remain readable at
`/freight-quote-revisions/{id}`. Route generation and comparison are durable async jobs.

CI adds the Phase 5 PostgreSQL suite, generated-contract drift and authenticated
browser acceptance without removing earlier lint, type, architecture or test gates.
The Phase 4 OpenAPI snapshot changes additively because it contains shared schemas.

## Verified Coverage and Limits

The full backend regression run passed 283 tests, with 12 PostgreSQL-only cases
skipped locally. The later targeted freight/dispatch/migration run passed 35 tests
with its PostgreSQL race skipped. PostgreSQL ran 30 freight/migration tests; the
subsequent typed-head regression and withdrawal/acceptance race both passed on
PostgreSQL. Frontend: 71 tests passed, plus build, type, lint and architecture
checks. The authenticated desktop/mobile walkthrough and local Postman CLI checks passed.

Direct Phase 5 tests cover fixed demo totals/exclusions/Pareto, waiting boundaries,
half-paise rounding, exact capacity and truck measurement bounds, state reentry,
immutable records, invitation-scoped unassigned evidence, durable generation,
UUID-head reads, price/driver masking, generic-endpoint bypass prevention, exact
acceptance expiry, atomic self-booking replacement, cancellation without goods-ledger
effects, stale old releases and a new release invalidated by dataset suspension.

This is not a claim that all 111 requested acceptance scenarios are individually
automated. Dedicated PostgreSQL races cover quote withdrawal versus acceptance,
duplicate idempotent acceptance and pickup versus incompatible commitment. Each
passed; the idempotent race returns one commitment and one context increment.
Broader allocation, amendment and dispatch concurrency retain their existing
suites. Additional Phase 5-specific cross-trade/amendment race permutations remain
a hardening task.

Production is intentionally fail-closed until a reviewed production dataset and
published Phase 4 scope cover the goods, profile and full corridor. Local checks
do not certify real permits, government APIs, physical measurements or legal rules.
Only `PERMITTED_ARCHIVE` datasets are accepted: time-limited/no-storage sources
are rejected until lawful expiry/purge support exists. Licensed geocoder results
are not silently accepted by the pin workflow.

Optional routing connections currently expose a server-side host/secret/capability
and retention boundary; executable live provider-route ingestion is not enabled.
Unconfigured/unapproved India-HGV connections fail explicitly, and missing corridor
coverage never becomes PASS. No claims of live traffic, map coverage or live ORS
capabilities are made. The retained textual comparison works without a map service.

News/weather ingestion, post-pickup rerouting, multi-vehicle optimisation, shared
payers, autonomous bookings, carrier payments/refunds and disruption prediction are
outside this phase. Quote-document references require explicit carrier adoption;
this phase does not add a freight-specific OCR model or automatically transform
an extracted document into a legally effective offer.
