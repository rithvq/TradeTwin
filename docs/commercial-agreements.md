# Phase 1: Commercial Agreements

## Boundary

Shipments owns organisations, declared registrations and locations, permissions,
commercial drafts, immutable revisions, offers, confirmations and amendments.
Evidence exposes the append-only agreement history. Documents, Compliance, Graph,
Risk, Optimizer and Regulations retain their existing shipment functions. The new
trade workspace links to each and displays a later-phase empty state where no
execution context exists. An agreement is not automatically converted into a
shipment or authorised for dispatch.

The supported agreement is an Indian interstate sale of goods, one Seller and one
Buyer organisation, one or more goods lines, INR prices and road delivery. The UI
always separates **Commercial agreement status** from **Dispatch readiness: Not
assessed**. No LLM, invoice processing, filing, risk model or route optimizer is
invoked by this phase. GSTIN checksum/format validation and user-confirmed HSN are
declarations, not proof of government verification or final tax treatment.

## Run

From PowerShell in the repository root, with Docker Desktop running:

```powershell
docker compose up -d --build --wait --wait-timeout 240
docker compose ps
powershell -ExecutionPolicy Bypass -File scripts/health-check.ps1
```

Open <http://localhost:3000/trades>. Existing OAuth sign-in and the private session
cookie are reused. The Shipment Service runs versioned additive Alembic migrations
at startup under a PostgreSQL advisory lock; it does not delete or change existing
shipment/document tables. Ledger tables have a `trade_` prefix except `trades`.
Migration version tracking uses `trade_alembic_version`, separate from platform
migrations. Existing document encryption keys and OAuth secrets are unchanged.

## Onboard Actual Parties

1. Each person signs in with their existing OAuth identity. The Business profile
   page shows the commercial user ID to share with their organisation administrator.
2. Create a business profile and fill its address/contact/registration declaration.
   Creation grants only `ORG_ADMIN`; it never grants commercial approval.
3. The administrator explicitly assigns operators and approvers using the member
   user IDs. Seller operator and approver can be different people. An organisation
   can hold buying and selling capabilities and participate on either side of
   different trades. Capabilities can also be trade-scoped/expiring via the API.
4. Select an organisation and Seller/Buyer view. The server validates the context;
   the interface role is only a filter and cannot grant approval.
5. Select the other onboarded organisation. A typed name or GSTIN cannot join or
   claim a business. Search exposes names, declared registration references and
   explicitly public trading locations, not private members, contacts or addresses.

## Completion Walkthrough

1. Seller operator selects **Create trade**, saves an incomplete draft, and fills
   the seven-step wizard. Autosaves create immutable revisions; conflict errors
   require explicit reload instead of overwriting newer work.
2. Add at least two goods lines, declared price/tax terms, payment terms, separate
   billing/movement addresses and delivery windows. Unit prices are decimal paise;
   quantities and rates travel as decimal strings. All totals are integer paise,
   rounded half-up on the server. Unknown tax is null, never a final payable amount.
3. Publish the offer with a future expiry. Publication freezes validated values,
   party snapshots and a server-generated SHA-256 terms hash. Both approvals are
   initially pending; publication implies no acceptance.
4. Seller approver reviews and accepts the precise offered revision. Buyer approver
   independently reviews the proposed address and accepts the same revision/hash.
5. The workspace displays the confirmed commercial agreement. Dispatch readiness
   remains Not assessed. Profile edits cannot rewrite the accepted snapshots.
6. Buyer operator supplies a reason and proposes an amendment from the accepted
   revision. Resume the candidate, change retained goods lines, and publish it.
   The original accepted agreement stays the primary view throughout this process.
7. Both approvers accept the amendment offer. Only the second matching acceptance
   atomically replaces the accepted agreement. Rejection/withdrawal preserves it.
8. Select **Evidence** to inspect actors, organisations, revisions, offers,
   timestamps, reasons and before/after summaries. General history omits GSTINs,
   addresses, email, bank data and session credentials from its generated summaries.

## APIs And Reliability

API prefix: `http://localhost:8011/api/v1`. Interactive OpenAPI is at `/docs`
(authenticate with an existing profile bearer session). All mutations require
`Idempotency-Key`. Organisation-scoped calls require `X-Organization-Id`. Edits,
publication, initial-offer withdrawal and amendment creation require quoted
`If-Match` ETags. Confirmations intentionally do not require approval-count ETags;
they target immutable offer/revision/hash values and lock the shared trade.

Identical successful retries return their original response. Changed payload or
actor with the same key returns `409 IDEMPOTENCY_KEY_REUSED`; stale ETags return
`412 REVISION_MISMATCH`; validation returns field paths under `error.field_errors`.
Read access and replayed mutations still validate active membership/capabilities.
PostgreSQL locks and partial unique indexes prevent duplicate active offers or
amendments. Composite foreign keys bind pointers, snapshots and approvals to the
correct trade and frozen party. Database triggers reject updates/deletes of
revisions, item revisions, snapshots, approvals and evidence. No endpoint deletes
accepted agreements or unilaterally cancels them.

Import `docs/postman/commercial-agreements.postman_collection.json` into Postman.
Set `profile_token`, `current_organization_id` and participant IDs per actor; never
commit tokens. Use a fresh idempotency key for a new action and the same key for a
retry. Generated scripts capture revision/offer/hash/ETag values. The included
OpenAPI JSON also contains full publication validators, not only draft schemas.
Postman initializes blank delivery/expiry variables with future UTC times once,
preserving the payload on retries. Update those variables for later new offers.

## Demo Fixtures And Reset

The seed command creates Seller/Buyer/unrelated organisations, five separate role
users, two products, and draft/offered/confirmed trades. It does not install a login
bypass or attach real people to businesses based on GSTIN.

```powershell
docker compose exec shipment-service python -m app.trades.cli
```

Default fixture identities have no OAuth login. To demonstrate interactively, use
five test OAuth accounts and supply an explicit administrator-controlled mapping
from `seller-operator`, `seller-approver`, `buyer-operator`, `buyer-approver`, and
`unrelated` to their existing OAuth profile IDs with `--identity-map '<JSON>'`.
Do this only in a disposable demo deployment. Repeated seeding preserves the same
fixture trade history; expired demo offers must be withdrawn and republished.

For a clean reset, the browser/acceptance scripts create and remove their own
temporary databases automatically. Do not delete production commercial evidence.
To reset a separately created Docker demo project, stop that project's containers
and remove only its own disposable volumes. Never run `down -v` against the primary
TradeTwin project to reset a demonstration.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest services/shipment-service/tests -q
docker compose run --rm --no-deps --build shipment-service python -c "import os,pytest; os.environ['TRADE_TEST_DATABASE_URL']=os.environ['DATABASE_URL']; raise SystemExit(pytest.main(['tests/test_commercial_agreements.py','-q']))"
cd apps/web
npm.cmd test
npm.cmd run build
cd ../..
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-browser.txt
.\.venv\Scripts\python.exe scripts/commercial-browser-check.py
```

The PostgreSQL suite creates random disposable schemas in the configured test
database and removes only those schemas. It verifies confirmation, withdrawal and
parallel amendment races. SQLite runs skip these PostgreSQL-specific race tests.
The browser suite uses genuine profile sessions in temporary auth databases, not
production authentication changes. It covers keyboard-operated wizard/review/
confirmation/amendment, mobile overflow, history, truthful future-module states,
and unrelated-organisation denial. Existing service and profile-isolation suites
remain in CI.

The local browser suite uses installed Chrome. For a machine without Chrome,
install Playwright Chromium with `python -m playwright install chromium` and set
`PLAYWRIGHT_CHANNEL=chromium`; CI uses this option. It does not require production
OAuth credentials or real customer documents.

## Changed Modules

- `services/shipment-service/app/trades/`: validators/reference data, independent
  ledger models, migrations, access checks, exact arithmetic/hashing, transactional
  state machine, organisation services, API composition and explicit demo CLI.
- `apps/web/components/trades/`, `apps/web/lib/trades.ts`, `apps/web/app/trades/`:
  commercial UI and request adapters; existing service interfaces remain intact.
- `apps/web/hooks/use-commercial-draft.ts`, `apps/web/lib/trade-draft.ts` and
  `wizard-fields.tsx` separate autosave/concurrency, initial data and field views.
- Next.js service proxy forwards organisation/concurrency/idempotency headers and
  PATCH; middleware protects the new pages; navigation adds Create trade.
- Acceptance tests, authenticated browser suite, generated API/Postman artifacts
  and CI's PostgreSQL ledger tests.

## Verification

Verified locally on 2026-10-11:

- Full backend regression suite: 103 passed; three SQLite race skips are covered
  separately in PostgreSQL.
- PostgreSQL commercial acceptance suite: all 34 passed, including competing
  confirmations, second-confirmation/withdrawal, parallel amendments and revoked
  or expired scoped approval permissions.
- Frontend: all 45 tests passed; production build, lint, formatting, TypeScript
  and both architecture checks passed.
- Authenticated desktop/mobile browser walkthrough passed the complete creation,
  independent confirmation, buyer amendment, replacement and evidence flow.
- Existing domestic service integration and private-profile isolation checks
  passed without changing document storage or earlier module behavior.
- Docker rebuild/startup completed with all ten services running. Web, OAuth
  provider discovery, backend readiness, Neo4j HTTP and MinIO readiness passed;
  the live database reports `trade_001` and five immutable-history triggers.

Not implemented: dispatch authorization, carrier booking, final HSN/tax treatment,
government filing, statutory authenticity checks, advanced OCR or LLM commercial
approval. Existing shipment features continue separately. Schema/account access
does not establish legal authority to represent a business; production onboarding,
business-authority verification, backups and appropriate administrator controls
remain deployment responsibilities.
