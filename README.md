# TradeTwin

## Route Memory

The Optimizer now opens profile-scoped route memory, reviewed carrier offers and dated
decision comparisons linked to shipment events, document readiness and regulation versions.
See [state-relations setup and limits](docs/state-relations.md) for optional truck routing,
refresh behavior and the distinction between quoted prices, observations and estimates.

## Confidential Documents

Document files and sensitive extracted metadata are encrypted at rest. Before starting
a fresh checkout, run `python scripts/init-document-key.py` once. Preserve and securely
back up `.secrets/document-keyring.json`; losing it prevents document recovery.
Read [rollout, migration and security limits](docs/confidential-documents.md) before
rebuilding an existing deployment.

## Source-Backed Rule Updates

The Regulations workspace supports official-source retrieval, optional AI drafting,
source quotations, administrator review and versioned publication. Set
`REGULATION_CATALOG_MODE=reviewed` to evaluate only database-published rules;
the default `demo` retains bundled scenarios. See
[configuration, workflow and limitations](docs/dynamic-regulations.md).

## India Domestic Scope

The primary workflow now covers domestic Indian road shipments, including
interstate movement, Indian locations, INR values, tax invoices and e-way bill
document readiness. See [India domestic scope and walkthrough](docs/india-domestic.md)
for coverage, migration, tests and limitations. The phase descriptions below
document the earlier international prototype retained for historical compatibility.

Profile login is now required by default. Follow [OAuth setup](docs/oauth-setup.md)
to configure sign-in and understand how existing data is preserved separately.

See [the functional audit and verification report](docs/audit-2026-09-08.md)
for tested workflows, runtime connectivity, repeatable checks, and prototype limitations.
TradeTwin is an AI-driven Digital Twin for Cross-Jurisdiction Trade Compliance.

This repository now includes Phase 7: project-evaluation readiness with reports, demo auth/RBAC, audit logs, documentation, tests, and a guided walkthrough. It still does not implement production OCR, live LLM extraction, real customs filing, or real customs rules.

## Stack

- Frontend: Next.js, TypeScript, Tailwind CSS
- Backend: FastAPI, Python 3.12, Pydantic Settings, SQLAlchemy, Alembic, pytest, Ruff
- Infrastructure: PostgreSQL with pgvector, Neo4j, Redis, MinIO

## Local Setup

```bash
docker compose up --build
```

For local overrides, copy `.env.example` to `.env` and export the values you want Compose to use.

Open:

- Web: http://localhost:3000
- Orbital dashboard: http://localhost:3000/dashboard
- API health: http://localhost:8000/health
- Shipment service health: http://localhost:8011/health
- Compliance service health: http://localhost:8012/health
- Document service health: http://localhost:8013/health
- Intelligence service health: http://localhost:8014/health
- Neo4j browser: http://localhost:7474
- MinIO console: http://localhost:9001

The orbital dashboard uses live shipment, compliance, risk, and service-health data
from the existing microservices. Aggregate values without a dedicated endpoint yet
(pending reviews, recent regulation changes, missing-document totals, graph
relationships, and route alternatives) are visibly marked as demo values.

Dashboard previews:

- [Desktop dashboard](docs/screenshots/tradetwin-dashboard-desktop.png)
- [Mobile dashboard](docs/screenshots/tradetwin-dashboard-mobile.png)

Default local Neo4j login:

- Username: `neo4j`
- Password: `123456789`

Default local MinIO login:

- Username: `tradetwin-local`
- Password: `123456789`

## Make Commands

```bash
make up
make down
make logs
make test
make health
```

`make test` runs each backend service test suite inside its Docker image.
`make health` checks the local web app, backend health endpoints, and seeded shipment API.

## Repository Structure

```text
apps/
  web/
  api/
services/
  shipment-service/
  compliance-service/
  document-service/
  intelligence-service/
packages/
  shared/
  domain/
infra/
docs/
data/
```

See [docs/architecture.md](docs/architecture.md) for planned service boundaries.

Evaluation docs:

- [API reference](docs/api.md)
- [Demo walkthrough](docs/demo-walkthrough.md)
- [Feature boundaries](docs/feature-boundaries.md)
- [Docker deployment guide](docs/docker-deployment.md)
- [Architecture diagram](docs/architecture-diagram.md)
- [Threat model](docs/threat-model.md)
- [Legal disclaimer](docs/legal-disclaimer.md)

## Phase 1 Shipment APIs

The Shipment Service runs on http://localhost:8011 and exposes:

- `POST /shipments`
- `GET /shipments`
- `GET /shipments/{id}`
- `DELETE /shipments/{id}`
- `POST /shipments/{id}/consignments`
- `POST /shipments/{id}/route-legs`
- `POST /shipments/{id}/events`
- `GET /shipments/{id}/timeline`
- `GET /shipments/{id}/graph`

The service seeds a demonstration shipment for the route India to UAE to Germany with lithium batteries bound for Germany and consumer electronics bound for UAE.

## Phase 2 Compliance APIs

The Compliance Service runs on http://localhost:8012 and exposes:

- `POST /compliance/evaluate/{shipment_id}`
- `GET /compliance/assessments/{shipment_id}`

Compliance results are generated from versioned JSON rules in `services/compliance-service/app/rules`. The mandatory demo distinguishes UAE import rules for unloaded consumer electronics from UAE transit rules for lithium batteries that remain in transit.

## Phase 3 Document APIs

The Document Service runs on http://localhost:8013 and exposes:

- `POST /shipments/{id}/documents`
- `GET /shipments/{id}/documents`
- `POST /documents/{id}/extract`
- `GET /documents/{id}`
- `GET /assessments/{id}/evidence`

Uploaded files are stored in MinIO and document metadata is stored in PostgreSQL. Extraction is limited to embedded PDF text or plain text fields for product name, quantity, declared value, country of origin, document number, and document date.

For the demo workflow, upload `data/demo-battery-safety-certificate.txt` as a safety certificate on the shipment's Documents page, extract metadata, then reevaluate compliance to see the UAE lithium transit evidence record.

## Phase 4 Consistency APIs

The Compliance Service also exposes deterministic consistency and questioning endpoints:

- `POST /consistency/check/{shipment_id}`
- `GET /shipments/{id}/questions`
- `POST /shipments/{id}/questions/{question_id}/answer`

The checker detects origin, HS code, invoice value, quantity, certificate, procedure, and route conflicts. The questioning endpoint returns only the highest-impact unresolved question first, such as whether the lithium battery consignment remains sealed onboard in UAE.

## Phase 5 Intelligence APIs

The Intelligence Service runs on http://localhost:8014 and exposes:

- `POST /intelligence/hs-classify`
- `POST /intelligence/risk-score/{shipment_id}`
- `GET /shipments/{id}/risk-assessment`

HS-code recommendations use a local seeded taxonomy and the default mock LLM gateway, so no API key is required. Risk prediction uses scikit-learn models trained from seeded synthetic examples and displays this warning: "Prototype prediction based on synthetic or organization-provided data."

## Phase 6 Optimization And Impact APIs

The Compliance Service also exposes deterministic route and regulation-change endpoints:

- `POST /optimizer/route-options/{shipment_id}`
- `POST /regulations`
- `POST /regulations/{id}/publish-version`
- `POST /regulations/impact-analysis`

The demo regulation endpoint creates a new UAE lithium transit safety-certificate version. After publishing it, impact analysis identifies affected active or planned shipments, re-runs compliance, and recommends either uploading the missing safety certificate or using an alternate compliant route.

## Phase 7 Evaluation Features

The Compliance Service adds:

- `GET /auth/me`
- `GET /reports/compliance/{shipment_id}?format=html`
- `GET /reports/compliance/{shipment_id}?format=pdf`
- `GET /audit-logs`
- `GET /demo/scenarios`

Demo authentication is token-based when `AUTH_REQUIRED=true`. Local evaluation keeps `AUTH_REQUIRED=false` so the UI works out of the box. Replace the demo tokens in `.env` before using auth checks beyond local evaluation.

The report export includes shipment data, consignment status, deterministic rule results, missing documents, corrective action, evidence records, route recommendation, and a legal disclaimer.
