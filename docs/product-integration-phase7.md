# Phase 7 Integration Status

**Status: bounded implementation, not final Phase 7 completion or pilot qualification.**
The Phase 6 foundation does not implement executable recovery, atomic recovery
amendments, approved stop anchors or guarded resume. Phase 7 cannot truthfully
demonstrate or qualify those missing capabilities. Its release gate deliberately
reports `FAIL`/`UNKNOWN`; neither an administrator nor an independent reviewer can
override those outcomes to activate a pilot.

## Working Integration

- The eight existing modules remain the navigation and business ownership boundaries.
- `GET /api/v1/trades/{id}/workspace` returns `TRADE_WORKSPACE_V1`. It derives current
  facts from the original agreement, allocation, receipt/inspection, manual-payment,
  freight, document, compliance and corridor modules. It never creates a second ledger.
- Quantities remain per line and UQC. Ordered, allocated, dispatched, net received,
  accepted, rejected, inspection-pending and final-short quantities are separate.
  Receipt corrections and inspection reversals use the existing authoritative logic.
- Goods finance is omitted without financial permission. Freight prices and comparison
  estimates have their own permission checks. There is no combined money total or
  global completion percentage; bank settlement, carrier payment and tax are not inferred.
- Carriers/drivers see only consignments allowed by the existing assignment guards.
  Document counts include only readable documents. Role selection is only a navigation hint.
- Tasks are derived, not completed by UI commands. Seen/snooze state belongs to the
  authenticated user and exact task basis. Changed bases invalidate prior state;
  blockers cannot be snoozed. Targets are allowlisted local routes.
- Replay supports recorded runs, freight commitments, dispatch authorisations and
  recovery assessments. Exact captured-input recomputation is registered only for
  TradeTwin baseline runs with a matching source/dependency engine manifest.
  Older/different engines return `UNSUPPORTED_ENGINE`. Missing inputs are not repaired
  with current-world data. Replay never issues movement permissions or commits plans.
- Replay/export jobs reuse the existing outbox, expiring leases and worker. Access is
  rechecked on execution and every read/download. Comparisons are same-trade and
  same-consignment, recipient-bound and reprojected for current permissions.
- Evidence exports are expiring, private **reference manifests only**. They do not copy
  confidential document bytes into another store. Public exports fail closed because
  simulation mode alone does not certify synthetic provenance. Full signed bundles and
  licensed-source export governance are not complete.
- Readiness records capture the server source/dependency/parser configuration,
  available frontend source fingerprint, migration, simulation rule registry,
  check-definition hashes and external generation. The service-only Docker image cannot
  fingerprint the deployed frontend artifact: that coverage is explicitly unavailable.
- There are 25 mandatory automated definitions and four manual-review definitions.
  Definition registration is not execution of those deployment suites. Missing observations
  stay `UNKNOWN`; executable recovery is `FAIL`. Manual statements do not change outcomes.
- Exact-result qualification requires a different authorised principal. Pilot scope
  revisions and independent reviews can be retained, but activation and transactional
  pilot admission are not implemented as a working pilot pathway.
- Deployment pause blocks new final agreement/assignment bindings and movement permission
  issuance/consumption. Existing unused permissions become stale through their dependency
  snapshot. Reads, incidents, arrival, receipts, inspection and payment reports are preserved.
  The application does not command a physical vehicle stop.
- The registered restore exercise uses isolated in-memory SQLite markers to demonstrate
  backup loss and generation mismatch. It does not restore production or establish RPO/RTO.

## Guided Demonstration

`/dashboard/evidence/demonstration` exposes the bounded `BOUNDED_JOURNEY_V1` catalog.
It creates a normal incomplete simulation draft as the actual signed-in principal,
reads independent dimensions, and records a blocked executable-recovery checkpoint.
It cannot impersonate another user, submit arbitrary URLs/code, inject outcomes or
install accepted/ready/committed business statuses. A successor creates a fresh workspace
and preserves the sealed predecessor and its receipts. Ordinary workflow approvals still
require their own real principals and permissions.

This is **not** the required 35-step primary scenario, in-transit recovery branch,
partial-delivery scenario runner or complete failure-branch catalog. Existing authenticated
Phase 5 acceptance still exercises quote comparison, exact approvals, carrier commitment,
atomic initial replacement and fresh guarded pickup through normal services.
The demo clock records forward demonstration timing only; it does not alter business,
OAuth, membership or grant time. Measurements do not claim operational time saved.

## Access And Operation

Assign explicit roles through existing organisation membership management:

| Role | Authority |
| --- | --- |
| `EVIDENCE_ANALYST` | Additional replay/private export authority; underlying party/assignment read grants still required; no price/spending grant |
| `READINESS_OPERATOR` | Read/queue assurance and retain manual review statements |
| `QUALIFICATION_REVIEWER` | Independently review exact results and pilot scopes |
| `DEPLOYMENT_OPERATOR` | Prepare scope, request pause/restore drill and activation; cannot bypass qualification |
| `DEMO_PRESENTER` | Own bounded demo workspace/run/clock; no underlying business approval grant |

Replay and export also require the normal trade/assignment and subject-read permissions.
Demo draft creation also requires the normal `trade.create` seller permission.
New roles confer no implicit administrator approval authority.
Global readiness, qualification, scope and deployment controls also require the current
organisation UUID in the server-only `TRADETWIN_CONTROL_ORGANISATION_IDS` allowlist.
Tenant membership administration cannot change that binding. Missing/invalid bindings
fail closed for control commands; an unconfigured diagnostic context grants no authority.

UI entry points: the trade's operations workspace, Evidence's guided simulation and
Regulations' deployment assurance. Privileged global screens do not require a specific trade.
Private reads/errors use `private, no-store`. The existing authenticated proxy retains its
origin checks and never accepts browser-supplied identity as a replacement for the session.

### External Generation

Development defaults preserve previous prototype workflows:
`TRADETWIN_REQUIRE_QUALIFICATION=false`. **This is an unqualified development mode,
not a production pilot.** Set the flag to `true` for production protection; current
recovery/admission gaps prevent new production binding and movement permission actions.

For Docker, provision once on the host:

```powershell
.venv\Scripts\python.exe scripts/operational-fence.py init --path .runtime/operational-controls/generation.json
```

Set the server-only `.env` path to `/run/tradetwin-controls/generation.json` and recreate
shipment-service/document-worker. Both mount the **directory** read-only, so atomic file
replacement is visible to both. For non-Docker runs use the host's absolute file path.
Configure the trusted control organisation UUID allowlist separately on the server.
A readiness-authorised context request registers the initial unqualified deployment head.

Exclude `.runtime/operational-controls` from business database/object backups and restore
sets. Keep the authority of this generation independent of restored business records.
Keep the server control-organisation binding outside that business restore set too.
During a real restore, pause first, rotate the external generation with the operator script,
restore business data only, reconcile all post-backup gaps, and requalify. A mismatch remains
protected; this increment does not implement the complete reconciliation/reactivation flow.
Never rotate merely to silence an error or copy an old generation back to make old tokens work.

No `.env`, document keyring, OAuth secrets or real business records were changed by this work.

## Verification

Recorded local results for this increment:

| Check | Observed Result |
| --- | --- |
| Full backend regression run | 314 passed, 14 optional skipped; subsequent added boundary tests validated separately |
| Product boundary suite | 16 passed on SQLite, including revoked-worker and server-bound control checks |
| Product + migration suite | 15 passed on disposable PostgreSQL |
| Frontend | 79 tests passed; production build, lint and typecheck passed |
| Architecture | Backend and frontend dependency/unused-module checks passed |
| Authenticated browser | Phase 5 + product replay/demo/reset/privacy passed; desktop and 360px screenshots inspected |
| Postman CLI | Local synthetic price/driver privacy checks passed, with `--no-report-events` |

The PostgreSQL test container was removed. Browser test services and fixture storage are
disposable and are stopped by their harness. Screenshots reside in `artifacts/audit/product`.
These results do not satisfy the separate deployment qualification matrix.

Relevant commands:

```text
pytest services/shipment-service/tests/test_product_integration.py
pytest services/shipment-service/tests/test_trade_migrations.py
python scripts/product-browser-check.py
python scripts/export-product-contracts.py
npm run lint
npm run typecheck
npm test
npm run build
```

## Outstanding Release Requirements

1. Complete Phase 6 acquisition/outage/retention semantics, fixed-point delay and
   worst-case scenario envelopes; atomic recovery booking/amendments/approvals,
   approved anchors, EWB remediation and one guarded recovery-resume event.
2. Implement the full actor-separated 35-step scenario and all requested branches;
   business virtual-time isolation and immutable scenario/checkpoint coverage.
3. Implement deployment-scoped registered assurance runners/evidence, production
   provider licensing/access/configuration checks, exact deployed artifact manifests,
   transactional pilot caps/admission, reactivation and full external restore fencing.
4. Finish full signed evidence bundles, public synthetic provenance/redaction and
   recipient/source-licence governance; broaden expensive-job throttling and telemetry.
5. Run the actual security/accessibility assessment, restore rehearsal and reference
   performance workload. Do not substitute unit-test duration for operational benchmarks.

Reference performance target is **unmeasured**: 50 authenticated sessions, 30 requests/sec
for 10 minutes, 100 organisations, 10,000 trades, 1,000 consignments, 30,000 documents and
500,000 audit events. Required latency percentiles, error rates, queue/lock metrics and
topology must be captured without disabling guards. RPO <=900s and RTO <=3600s are
unverified targets, not guarantees.

Security review target: [OWASP ASVS 5.0](https://owasp.org/projects/asvs).
Accessibility review target: [WCAG 2.2 AA](https://www.w3.org/TR/WCAG22/).
The inspected new screens have keyboard/focus support and scoped 44px controls; that
is not a comprehensive WCAG/ASVS conformance claim.
