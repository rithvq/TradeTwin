# Codebase Maintenance

Audit and cleanup: 2026-10-11. Scope: improve maintainability and repair defects
without redesigning the UI, changing compliance conclusions, replacing prediction
algorithms, removing supported workflows or changing public API contracts.

## Module Ownership

| Area | Responsibility |
| --- | --- |
| `apps/api/app/auth.py` | OAuth, profiles, session creation and revocation |
| `packages/security` | Shared profile authorization and tenant ownership |
| `services/shipment-service/app/service.py` | Shipment persistence and event-state transitions |
| `services/shipment-service/app/graph.py` | Neo4j projection and graph response construction |
| `services/compliance-service/app/main.py` | Application composition, lifecycle, middleware and health |
| `services/compliance-service/app/routers/` | HTTP contracts, validation and authorization per workflow |
| `services/compliance-service/app/assessments.py` | Assessment orchestration, evidence and audit coordination |
| `services/compliance-service/app/assessment_repository.py` | Stored answers and assessment serialization |
| `services/compliance-service/app/evaluator.py`, `domestic.py`, `consistency.py`, `optimizer.py` | Existing deterministic domain algorithms |
| `services/compliance-service/app/regulations.py`, `regulatory_sources.py`, `state_relations.py` | Versioned regulation workflows, reviewed sources and operational memory |
| `services/document-service/app/` | Document metadata, parsing, encryption, object storage and evidence |
| `services/intelligence-service/app/` | Existing classification gateway, synthetic risk and persistence |
| `apps/web/app/` | Route entry points and page composition |
| `apps/web/hooks/` | Shipment-detail and route-memory state, loading and action orchestration |
| `apps/web/components/shipments/`, `components/routes/` | Focused workflow panels and carrier-offer form |
| `apps/web/lib/api/http.ts` | Shared JSON, multipart and binary HTTP response handling |
| `apps/web/lib/graph/shipment-layout.ts` | Pure node placement, relationship families and graph labels |
| `apps/web/lib/state-relations.ts` | Route-memory API types and its structured error handling |

HTTP routers call domain services, not the application entry point. Pure evaluators
must not import HTTP routers. Frontend libraries/types must not import pages,
components or hooks. Presentation consumes controllers; controllers consume typed
API modules. Type-only panel/controller imports do not create runtime coupling.
Services remain independently owned; no new generic microservice framework was added.

## Cleanup And Fixes

- Split compliance HTTP endpoints, assessment orchestration and storage helpers
  out of the application entry point. Its 27 existing OpenAPI operations retain
  their paths, methods, operation IDs, request contracts and response declarations.
- Split shipment details into feature panels and a controller hook; separate
  graph layout from rendering; separate route-memory state and the carrier form.
  Component markup and workflow actions are retained.
- Remove the unreachable international shipment-creation component and obsolete
  international smoke-test function. The active domestic form, demo loading and
  legacy record evaluation/rule tests remain. International shipment creation
  remains intentionally rejected by the existing India-domestic API contract.
- Standardize formatting, enable unused TypeScript checks, remove unused imports,
  ignore generated audit artifacts and add automated dependency-direction checks.
- Fix Docker tests so each backend receives the shared test configuration and
  security package. Use a separate frontend test image; production contains only
  production Node dependencies. `make test` rebuilds the sources being tested.
- Fix health checks to respect configured ports and authenticated deployments.
  No protected-data endpoint is required to be publicly accessible.
- Fix Windows integration-server shutdown: terminate the owned test-process tree
  so venv interpreter children release temporary SQLite databases before cleanup.
  HTTP smoke tests require isolated local stores and remove their graph fixtures
  before shutdown. The older browser entry point delegates to the current domestic
  walkthrough instead of maintaining broken international-only assertions.
- Fix PostgreSQL risk-scoring failures: the full domestic disclaimer exceeds the
  former `VARCHAR(160)` column. Store it as `TEXT`; an idempotent startup migration
  widens existing PostgreSQL columns without changing stored warnings or scores.
- Upgrade Next.js to 15.5.27, React/React DOM to 19.1.9 and affected dependencies.
  The original Next.js version was covered by a
  [critical upstream security advisory](https://github.com/vercel/next.js/security/advisories/GHSA-9qr9-h5gf-34mp).
- Update the default ORS routing URL to the provider's current host, retaining
  explicit consent, vehicle restrictions and coordinate-only requests. The old
  host has reduced quotas according to the
  [provider migration notice](https://ask.openrouteservice.org/t/reducing-the-quota-of-deprecated-api-api-openrouteservice-org/8013).

## Verification

- Backend: 72 unit/contract tests pass locally and in the five service images.
- Frontend: 36 tests covering navigation, proxies, graph layout, shared HTTP
  transport, detail actions and route-memory monitoring.
- Ruff, ESLint, strict TypeScript and formatting checks pass.
- Architecture checks cover all service application modules and web modules,
  checking cycles, unresolved local imports and disallowed dependency directions.
- Production Next.js builds pass locally and in Docker.
- Isolated HTTP integration verifies domestic creation/delivery, encrypted
  uploads and extraction, independent consignment outcomes, provenance, route
  comparison, risk persistence, regulation impact and HTML/PDF reports.
- The infrastructure variant uses a disposable PostgreSQL database and MinIO
  bucket on the running containers; it verifies Neo4j projection and Redis job
  persistence. Existing user databases, documents and encryption keys are retained.
- Profile integration verifies cross-profile denial, forged/expired sessions,
  private documents, evidence, reports and risk, plus logout revocation.
- Browser checks exercise desktop/mobile creation, demo navigation, graph
  framing, classification, compliance, risk, route comparison, PDF download,
  reviewed carrier offers, regulatory review and profile/login boundaries.
- Compose startup and public health/readiness checks are verified.

These checks are regression evidence, not a guarantee that every possible input,
external outage or legal interpretation is covered.

## Repeatable Checks

Local commands assume the existing Python venv contains all service requirements
and the editable security package, and `npm ci` has been run in `apps/web`.
On Unix, substitute the appropriate venv executable and `npm` for Windows commands.

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api services packages scripts conftest.py
.\.venv\Scripts\python.exe -m ruff format --check apps/api services packages scripts conftest.py
.\.venv\Scripts\python.exe scripts/check-architecture.py
.\.venv\Scripts\python.exe -m pytest apps/api services
npm.cmd --prefix apps/web run lint
npm.cmd --prefix apps/web run typecheck
npm.cmd --prefix apps/web run format:check
npm.cmd --prefix apps/web run check:architecture
npm.cmd --prefix apps/web test
npm.cmd --prefix apps/web run build
npm.cmd --prefix apps/web audit --omit=dev --audit-level=high
.\.venv\Scripts\python.exe scripts/smoke-test.py --local
.\.venv\Scripts\python.exe scripts/profile-security-check.py
.\.venv\Scripts\python.exe scripts/domestic-browser-check.py
.\.venv\Scripts\python.exe scripts/profile-browser-check.py
```

Docker and real-infrastructure checks:

```powershell
docker compose up -d --build --wait --wait-timeout 240
make test
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/health-check.ps1
.\.venv\Scripts\python.exe scripts/smoke-test.py --local --infrastructure --port-offset 27000
```

Browser checks require Chrome and Playwright. They start isolated services and
stop them afterward. If test ports are occupied, `--port-offset` is available for
HTTP checks; the domestic browser check accepts `BROWSER_SERVICE_OFFSET` and
`BROWSER_WEB_PORT`. Never disable profile authentication on the real deployment
just to run tests. Tests use explicit isolated configurations instead.

## Remaining Limits

The production npm audit reports zero vulnerabilities at verification time. The
full development dependency audit still reports six high-severity findings in
the ESLint/braces dependency chain; those packages are excluded from the production
web image. No breaking lint-stack downgrade was forced to hide these findings.
Keep reviewing upstream fixes and lint only trusted repository inputs.

Authlib and Starlette emit upstream deprecation warnings during backend tests.
They do not fail the suites; future dependency migrations should retain OAuth
and concurrency regression coverage.

Google OAuth callbacks, LLM responses, source retrieval and ORS requests are
mocked for automated tests where necessary. This audit does not prove external
provider availability, API-key validity or document/legal accuracy for unseen
formats. No paid provider requests or confidential-document submissions to LLMs
were made. Existing demo/production distinctions and safety disclaimers remain.
