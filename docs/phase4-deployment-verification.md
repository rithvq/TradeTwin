# Phase 4 Deployment Verification

Local deployment checked on 2026-10-13. This report records observed checks, not a
certification of current Indian law or production readiness.

## Deployment

- Application: `http://localhost:3000`; sign-in: `/login`.
- Shipment Service OpenAPI: `http://localhost:8011/docs`.
- Rebuilt the web, API, shipment, document, compliance, intelligence and document-worker images.
- Upgraded the existing commercial database from `trade_002` through `trade_004`.
- Preserved existing PostgreSQL, MinIO, Neo4j and Redis volumes and the encryption keyring.
- Created the missing worker credential using `scripts/init-document-key.py`.
- Fixed Windows secret-file owner permissions without broadening access to Everyone.
- Main deployment uses real PostgreSQL, Redis, Neo4j, MinIO and ClamAV containers.

## Recovery Checks

Pre-upgrade database and stopped-volume archives are in the ignored local directory
`.backups/phase4-20261013`. The separate recovery-key copy remains under `.secrets`.
Both directories stay out of Git and Docker build contexts. Protect backups as
confidential data and copy them to appropriately protected recovery storage.

The PostgreSQL archive was restored successfully into a disposable, network-disabled
container. Trade, revision, audit, consignment, movement, receipt and profile counts
matched the upgraded database. Encryption-keyring hashes matched before/after.
MinIO/Neo4j/Redis archives were created, but a complete multi-service disaster-recovery
exercise was not performed. The disposable restore-check container was removed.

## Verified Checks

| Check | Observed result |
| --- | --- |
| Docker image build, including production Next.js build | Passed |
| Web login, API health, four service readiness endpoints and sign-in provider endpoint | Passed |
| Document-worker heartbeat, ClamAV, PostgreSQL and Redis container health | Passed |
| MinIO readiness and Neo4j connectivity through Shipment Service readiness | Passed |
| Phase 4 endpoint registration and unauthenticated registry rejection | Passed |
| Deployed website login, configured provider, private-page redirect and desktop/mobile rendering | Passed; no browser runtime errors |
| Real ClamAV INSTREAM scan of harmless test bytes | Passed |
| Actual MinIO AES-GCM round trip and rejection of incorrect encryption context | Passed; temporary object removed |
| Full backend suite | 250 passed, 11 PostgreSQL-only cases skipped, two dependency deprecation warnings |
| PostgreSQL migration, commercial, operational, document and guarded-dispatch suite | 170 passed, no skips; one dependency deprecation warning |
| Frontend unit tests | 62 passed in 12 files |
| Authenticated guarded-dispatch browser walkthrough | Passed |
| Local Postman read-only smoke, with reporting disabled | Passed; temporary credentials discarded |
| Backend/web architecture checks, lint, formatting and generated contracts | Passed |

The PostgreSQL-only cases skipped in the full backend run were exercised in the separate
PostgreSQL suite. Its disposable container was removed after completion; the main
deployment remains running.

The authenticated browser run verified an explained missing-EWB blocker, independent
review, an encrypted carried-document download, assignment-bound packet, driver
acknowledgement, separate atomic pickup/departure and immutable consumed-authorisation
evidence. Desktop/mobile screenshots were captured under ignored `artifacts/audit/dispatch`.
Its authority responses/signatures are explicitly SIMULATION fixtures and its scanner
transport is stubbed. The separate real-container storage/scanner checks above do not
use that scanner fixture.

## Recheck

```powershell
docker compose ps
powershell -ExecutionPolicy Bypass -File scripts/health-check.ps1 -GuardedDispatch
```

## Limits

- Production regulation candidates are not automatically published or legally approved.
- Live transport-authority integrations, universal PDF-signature trust and government
  filing/clearance are not supplied by this phase. Missing evidence fails closed.
- An actual external OAuth-provider login/callback was not exercised during this
  deployment; provider configuration, sign-in availability and protected routes were checked.
- The 111 requested acceptance scenarios have not been individually certified. Tests
  cover the named boundary, privacy, stale-evidence, concurrency and release workflows,
  not every real-world commodity, corridor or statutory exception.
- Publisher diff presentation and a single automated wrong-document/correction/expiry/
  refresh demonstration remain follow-up work. Do not describe synthetic outcomes as
  live government decisions.
- HTTPS deployment, managed key custody, external immutable audit storage, security
  testing, current-source legal review and full disaster recovery remain commercial
  deployment requirements.

See [Phase 4 architecture and runbook](guarded-dispatch-phase4.md).
