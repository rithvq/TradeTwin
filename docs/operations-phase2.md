# Operational Phase 2

This is the domestic commercial lifecycle phase built on commercial Phase 1,
not a replacement for the existing legacy shipment/compliance features.
There are still eight top-level modules. Payments stay within Shipments.

## Local Start

In PowerShell, from the repository root:

```powershell
docker compose up -d --build --wait --wait-timeout 240
docker compose ps
```

Open http://localhost:3000/trades and sign in with the existing OAuth provider.
Shipment API documentation: http://localhost:8011/docs.
Use the accepted agreement's **Trade operations** link to allocate consignments.

No routing, bank or government credentials are needed for this phase.
Keep the existing OAuth configuration and document encryption key. Never change
that key merely to rebuild containers, and never use `down -v` to restart them.

## Development Simulation

Normal trade creation always creates PRODUCTION records. There is no public
mode-changing or reset endpoint. New production movement, receipt and closure
transitions return `409 DISPATCH_GATE_NOT_IMPLEMENTED`; preparation and
assignment remain available. Existing legitimate legacy tracking is unchanged.

Explicitly opt in for a development seed command:

```powershell
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --namespace phase2
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --namespace phase2 --reset --scenario complete
```

The first command creates a confirmed SIMULATION agreement ready for the UI.
The second runs the complete domain workflow and prints IDs and final totals.
`--reset` creates a new namespace; it never deletes previous records, financial
entries, original evidence or production data. Rerunning an already operated
namespace requires `--reset` rather than silently duplicating the lifecycle.

Seed-only identities are not login accounts. For manual multi-role UI evaluation,
map roles to **distinct existing OAuth profile IDs** from the normal `/auth/me`
response, using the CLI's JSON `--identity-map` argument. Do not use email,
OAuth client IDs, fabricated headers, or another authentication system.
Partial maps are supported; unmapped roles remain non-login fixture identities.
Do not map both financial counterparties to the same identity.

Supported role keys and authority:

| Role Key | Organisation | Authority |
| --- | --- | --- |
| seller-operations | Seller | Allocate, prepare, cancel before pickup, coordinate assignments |
| seller-approver | Seller | Phase 1 commercial approval |
| buyer-receiver | Buyer | Receive, correct, close and reopen physical delivery |
| buyer-approver | Buyer | Phase 1 commercial approval |
| buyer-inspector | Buyer | Independent acceptance, rejection and full decision reversal |
| buyer-finance | Buyer | Schedule proposal/approval and manual outgoing reports |
| seller-finance | Seller | Schedule proposal/approval, acknowledgment, allocation/reversal |
| carrier-dispatcher | Carrier | Own profile, vehicles, carrier consent and owned drivers |
| driver-one, driver-two | Carrier | Only current assigned movement/evidence tasks |
| unrelated | Unrelated | Denied access to the trade and its operations |

An organisation admin does not automatically gain finance or inspection authority.
The UI role selector only chooses between existing capabilities. Server checks
membership, explicit permission, participant side and assignment/resource ownership
on every request and before replaying an idempotent result.

Exception seeds are independently resettable:

```powershell
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --reset --scenario capacity
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --reset --scenario double-allocation
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --reset --scenario short
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --reset --scenario rejected
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --reset --scenario correction
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --reset --scenario carrier-access
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --reset --scenario payment-dispute
docker compose exec -e OPERATIONAL_DEMO_ENABLED=true shipment-service python -m app.operations.cli --reset --scenario overapplied
```

The double-allocation fixture requires PostgreSQL and asserts one successful
60-NOS reservation and one conflict. The overapplied fixture preserves the
1,000,000-paise allocation while a bilateral price amendment lowers the
obligation to 800,000 paise, exposing 200,000 paise OVERAPPLIED.

## Walkthrough

1. View the accepted 100-NOS agreement: unit 10,000 paise, discount zero,
   quoted goods total 1,000,000 paise; NET_TAX_EXTRA, additional tax unknown.
2. Allocate 40 and 60 NOS. Available quantity is zero; one further NOS fails.
3. Prepare each consignment and propose the carrier. A proposal is not consent.
4. Carrier dispatcher accepts owned vehicles and two active drivers.
5. Each driver records pickup, departure and arrival from their mobile task.
6. Buyer receiver records 20 + 20 for the first consignment and 60 for the second.
   Close physical delivery recording; this does not accept the goods.
7. Buyer inspector independently accepts all effective receipt lines.
8. Both finance parties approve the same goods schedule hash.
9. Buyer finance reports 1,000,000 paise. It stays MANUAL_REPORTED.
10. Seller finance acknowledges and allocates the paise to the goods obligation.
11. Inspect Evidence, Graph, operational exceptions and versioned planning inputs.

Final quantities: ordered 100, received 100, independently accepted 100.
Allocated goods amount: 1,000,000 paise. Provider verification, final invoice
reconciliation and statutory dispatch readiness all remain NOT_ASSESSED.

## States And Invariants

- Agreement status remains the Phase 1 commercial status; payment/movement is separate.
- Preparation: DRAFT / PREPARING / NEEDS_REVIEW / CANCELLED.
- Alignment: CURRENT / REVIEW_REQUIRED. Review-required plans must be cancelled
  and recreated before pickup, retaining their historical source snapshot.
- Movement: NOT_STARTED -> PICKED_UP -> IN_TRANSIT -> ARRIVED -> DELIVERY_CLOSED.
- Assignment: PROPOSED / ACCEPTED / DECLINED / SUPERSEDED / CANCELLED.
- Receipt totals come only from the effective head of each immutable receipt chain.
- Inspection totals come from append-only decisions minus complete reversals.
- Receipt correction requires reversal of effective inspections and reopening
  of an existing closure. Old closures and correction history are never overwritten.
- Rejected goods are still received; short/rejected goods never release order allocations.
- Disputes resolve only when both parties accept the exact same proposal. They
  do not automatically return goods, amend terms, change quantities or refund funds.
- Schedule content and lines are immutable; two exact-hash approvals activate it.
- Only the accepted quoted goods amount is scheduled; unresolved tax/freight stays unknown.
- Percentage rounding uses deterministic largest-remainder paise allocation.
- FULL_DISPATCH requires departure of all goods, not merely pickup. FULL_DELIVERY
  uses physical receipt, including rejected goods; FULL_ACCEPTANCE is independent.
- Trigger retractions retain original dates/history and require schedule review.
- Acknowledged funds are allocated atomically within both payment and obligation limits.
- Partially reversing an allocation cannot exceed its remaining original amount.
- Bilateral payment-record void reverses remaining allocations; it transfers no money.
- Funded obligation references survive replacement, even with a zero face amount.
- Quantities are numeric(20,6) decimal strings; money is bigint INR paise strings.
  UTC is persisted and IST is shown in operational forms. Unknown never means zero.

Trade-first PostgreSQL locks serialize stable-line reservations and payment limits.
Explicit vehicle/driver locks prevent overlapping bookings across different trades.
Mutable edits use `If-Match`. Every material mutation and its audit evidence are
committed with the existing idempotency transaction. Client event/receipt UUIDs
also detect changed-content retries.

## Eight Modules

| Module | Phase 2 Contribution |
| --- | --- |
| Shipments | Allocation, carrier consent, mobile movement, receipt, inspection, disputes, payments |
| Documents | Encrypted original-byte attachments with upload/security/authenticity status |
| Compliance | Preparation separate from dispatch readiness NOT_ASSESSED |
| Graph | Permission-filtered relational connections through operational and financial records |
| Risk | DECLARED/REPORTED exceptions linked to their source, not a universal score |
| Optimizer | Hashed schema-v1 planning inputs; no invented route, savings or prices |
| Regulations | State, HSN, cargo and movement context; no legal clearance inferred |
| Evidence | Append-only actor/time/resource records with SIMULATION labels |

## Evidence Security

Shipment Service owns metadata and authorisation; Document Service owns encrypted
MinIO bytes. PDF/JPEG/PNG uploads are capped at 20 MiB, checked for signature/size,
and SHA-256 is calculated from the original bytes on the server. Parallel writes
cannot replace an existing original. No extraction/OCR is performed on these files.

Set `EVIDENCE_CLAMAV_HOST` and `EVIDENCE_CLAMAV_PORT` to an accessible ClamAV INSTREAM
scanner in development/deployment. An absent, failing or inconclusive scanner
leaves evidence QUARANTINED, not CLEAN. Quarantined/rejected files cannot be
downloaded or linked as available evidence. Clean downloads require short-lived
profile/organisation-bound authorisation and a fresh integrity check.

Uploaded evidence is **authenticity not assessed**, including payment screenshots.
This does not establish statutory validity, bank verification, vehicle permits or insurance.
Carrier/driver access excludes trade pricing, financial records and payment evidence.
Superseded carriers/drivers lose current tasks; their own historical assignment
evidence is separately available at `/api/v1/assignments/{id}/evidence`.

## API Contracts And Tests

All routes are under `/api/v1`. Use the existing OAuth bearer session and
`X-Organization-Id`. Mutations require `Idempotency-Key`; mutable transitions also
require the current quoted ETag in `If-Match`. Errors preserve a request ID and
field paths. See `docs/postman/operations-phase2.openapi.json` and the 40-request
`operations-phase2.postman_collection.json` for the 40/60 lifecycle and critical failures.
Collection credentials default blank; use a fresh seed namespace before replaying.

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api services/shipment-service services/compliance-service services/document-service services/intelligence-service
.\.venv\Scripts\python.exe -m pytest services/shipment-service/tests/test_operations.py
.\.venv\Scripts\python.exe scripts/export-operations-contracts.py
.\.venv\Scripts\python.exe scripts/operations-browser-check.py
npm.cmd --prefix apps/web test
```

Set `TRADE_TEST_DATABASE_URL` to a disposable PostgreSQL test connection for race
tests. Tests create/remove only randomly named schemas; SQLite runs skip those
cases. Browser tests create real hashed sessions in isolated temporary databases,
start the existing services/Next.js, and operate role-specific screens on desktop
and mobile. No test-login endpoint or production identity header was added.

CI runs lint/format, frontend build/tests, existing integration/security checks,
PostgreSQL commercial/operational concurrency and authenticated browser walkthroughs.
No production dispatch, filing, OCR, bank transfer/refund, final invoice reconciliation,
new route optimiser or automatic return shipment is delivered by this phase.
