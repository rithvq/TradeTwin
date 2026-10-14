# Phase 6 Implementation Status

This is the **corridor-intelligence foundation**, not completion of the full
Phase 6 specification. It must not be represented as an executable recovery or
live nationwide alert service.

## Implemented

- Additive `trade_006` migration: source connections and exact versions,
  mapping/effect-policy revisions, independent governance actions, incidents,
  event revisions/actions, upstream tombstones, scoped epochs, source-health
  records, coverage/impact snapshots, cases and driver responses.
- Retained revisions/actions/assessments are database-immutable. Governance
  actions have deterministic sequence numbers, independent of timestamp ties.
- Dedicated clean secured source artifacts, explicit provenance, archival
  licensing boundary, no reuse of confidential business-document attachments.
- Organisation capabilities, exact-hash independent review/publication,
  mutation idempotency, mutable-head ETags and execution-mode isolation.
- Bounded CAP 1.2 XML parser rejects DTD, entities, external resources and
  XInclude. IMD nowcast and district-warning parser contracts use different
  severity maps, preserve source dates and never equate provider IDs with GST
  state codes. Parsing does not publish events.
- Exact dataset/edge and direction matching, real Shapely polygon intersection,
  administrative/unknown-geography limitations and half-open traversal windows.
  Retained topology nodes are not substituted for actual road geometry.
- Source age and effect-policy boundaries are evaluated using trusted time.
  Expiry, withdrawal, cancellation or outage do not prove reopening. Independently
  published positive reopening evidence must cover the original exact scope.
- Relevant route-scoped publication epochs stale frozen runs and releases.
  Phase 5 candidate feasibility includes captured corridor projections. The
  carrier's fixed quote and commercial-context hash do not change due to news.
- Phase 4 dependency capture, authorisation issuance and consumption inspect
  corridor impacts synchronously under the existing shared registry lock;
  publication uses its exclusive side. Uncertain/blocked impacts cannot release
  movement. Provider calls never occur inside these transactions.
- Retained current-route impact assessments, detection cases, and assigned-driver
  reports distinguish protection from physical stopping. Reports are not verified
  locations, spending approvals, or resume permissions. Historical motion reports
  remain recordable without overwriting newer motion.
- Existing Shipments, Compliance, Risk, Optimizer, Regulations and Evidence
  screens expose these records. The driver task exposes the price-free corridor
  desk. No ninth module is introduced.

## Deliberately Disabled or Pending

- Live fetch workers, automatic polling, conditional 200/304 cache validation,
  rate-limit/backoff/dead-letter handling, licensed news and retention/purge
  enforcement. Live source configuration fails closed with `ADAPTER_NOT_ENABLED`.
  Manual archival ingress works; it does not establish exhaustive coverage.
- Automatic official-adapter publication, full cross-source clustering/conflict
  resolution, scoped advisory locks beyond the conservative existing registry
  publication barrier, and the full alert outbox/recipient/seen/acknowledgment flow.
- Full fixed-point delayed-window assessment, mandatory scenario envelopes and
  nominal/worst-case objectives. Current delays are disclosed operational ranges,
  not probabilistic predictions or guaranteed worst-case bounds.
- Fresh approved stop anchors, recovery budgets, amendment-purpose RFQs/quotes,
  exact recovery approvals, entire-service fixed-price replacement, atomic
  booking extension and execution revisions, effective-contract heads/backfill.
- Phase 4 `RECOVERY_RESUME`, `RECOVERY_RESUMED`, EWB remediation, recovery evidence
  manifests and all three complete recovery demonstrations. No endpoint in this
  increment can activate a recovery plan or issue a resume token.
- The full 111-case acceptance matrix, PostgreSQL race acceptance, live-provider
  acceptance and dedicated Phase 6 browser walkthrough remain incomplete.

Current assessments are bounded synchronous commands (`201`), not queued
reassessment jobs. Phase 5 runs continue using the existing durable worker.
Existing payments, invoices, goods allocations and transport contracts are not
rewritten by this foundation.

## Source Contracts

- [IMD API reference](https://api.imd.gov.in/public/api_reference.html): separate
  district nowcast and district warning color contracts.
- [OASIS CAP 1.2](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html):
  sender/identifier/sent identity, message type/status and references.
- [Sachet agency integration guide](https://sachet.ndma.gov.in/docs/Integration_Guide_For_Agencies.pdf):
  integration documentation, not blanket permission to invent a closure API.
- [Shapely manual](https://shapely.readthedocs.io/en/stable/manual.html) and
  [defusedxml](https://pypi.org/project/defusedxml/): pinned geometry/XML libraries.

## Verification Commands

```powershell
.venv\Scripts\pytest.exe services/shipment-service/tests/test_corridor_intelligence.py
.venv\Scripts\pytest.exe services/shipment-service/tests/test_trade_migrations.py
.venv\Scripts\python.exe scripts/export-corridor-contracts.py
```

Generated contracts: `docs/postman/corridor-intelligence.openapi.json` and
`corridor-intelligence.collection.json`. No credentials are included.

Recorded validation for this increment: 303 backend tests passed (14 optional
tests skipped), 74 frontend tests passed, production frontend build, lint,
typechecking, formatting, backend/web architecture checks, authenticated Phase 5
desktop/mobile regression and synthetic local Postman privacy checks passed.
These results do not constitute full Phase 6 acceptance.

Final targeted checks: 21 corridor tests passed on SQLite; 23 corridor/migration
tests passed against a disposable PostgreSQL instance. The development preview
was started with existing project volumes intact and confirmed at `trade_006`.
