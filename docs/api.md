# TradeTwin API Reference

TradeTwin exposes service-level APIs directly in the local Docker demo.

## Authentication

Compliance Service endpoints support demo bearer-token authentication.

Environment variables:

- `AUTH_REQUIRED=false` by default for local evaluation.
- `TRADETWIN_VIEWER_TOKEN`
- `TRADETWIN_OPERATOR_TOKEN`
- `TRADETWIN_ADMIN_TOKEN`

When `AUTH_REQUIRED=true`, send:

```http
Authorization: Bearer <token>
```

Role summary:

- `viewer`: read assessments, questions, route options, and reports.
- `operator`: viewer access plus compliance evaluation and question answers.
- `admin`: operator access plus regulation publishing and audit logs.

## Shipment Service

Base URL: `http://localhost:8011`

- `GET /health`
- `POST /shipments`
- `GET /shipments`
- `GET /shipments/{id}`
- `DELETE /shipments/{id}`
- `POST /shipments/{id}/consignments`
- `POST /shipments/{id}/route-legs`
- `POST /shipments/{id}/events`
- `GET /shipments/{id}/timeline`
- `GET /shipments/{id}/graph`

## Compliance Service

Base URL: `http://localhost:8012`

- `GET /health`
- `GET /auth/me`
- `POST /compliance/evaluate/{shipment_id}`
- `GET /compliance/assessments/{shipment_id}`
- `POST /consistency/check/{shipment_id}`
- `GET /shipments/{shipment_id}/questions`
- `POST /shipments/{shipment_id}/questions/{question_id}/answer`
- `POST /optimizer/route-options/{shipment_id}`
- `POST /regulations`
- `POST /regulations/{id}/publish-version`
- `POST /regulations/impact-analysis`
- `GET /reports/compliance/{shipment_id}?format=html`
- `GET /reports/compliance/{shipment_id}?format=pdf`
- `GET /audit-logs`
- `GET /demo/scenarios`

FastAPI interactive docs are available at `http://localhost:8012/docs`.

## Document Service

Base URL: `http://localhost:8013`

- `GET /health`
- `POST /shipments/{id}/documents`
- `GET /shipments/{id}/documents`
- `POST /documents/{id}/extract`
- `GET /documents/{id}`
- `POST /assessments/{id}/evidence`
- `GET /assessments/{id}/evidence`

## Intelligence Service

Base URL: `http://localhost:8014`

- `GET /health`
- `POST /intelligence/hs-classify`
- `POST /intelligence/risk-score/{shipment_id}`
- `GET /shipments/{shipment_id}/risk-assessment`

Risk output must display this warning:

```text
Prototype prediction based on synthetic or organization-provided data.
```
