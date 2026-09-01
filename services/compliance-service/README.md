# Compliance Service

Deterministic compliance engine for TradeTwin with evidence output, consistency checks, route optimization, regulation impact analysis, reports, demo RBAC, and audit logs.

This service evaluates shipments against versioned JSON and admin-published demo rules. It does not use LLMs, OCR, live customs filing, or real customs rules.

## Endpoints

- `GET /health`
- `GET /auth/me`
- `POST /compliance/evaluate/{shipment_id}`
- `GET /compliance/assessments/{shipment_id}`
- `POST /optimizer/route-options/{shipment_id}`
- `POST /regulations`
- `POST /regulations/{id}/publish-version`
- `POST /regulations/impact-analysis`
- `GET /reports/compliance/{shipment_id}?format=html`
- `GET /reports/compliance/{shipment_id}?format=pdf`
- `GET /audit-logs`
- `GET /demo/scenarios`

## Demo Rule Scope

The demo rules cover India, UAE, and Germany for export, transit, import, lithium battery safety certificates, certificate of origin, temporary storage, transshipment, and basic restricted-goods screening.

In Phase 3, the service can pull extracted document metadata from the Document Service and creates evidence records for the rules, regulation versions, supporting documents, missing documents, and triggering shipment events behind each assessment.

Phase 4 adds:

- `POST /consistency/check/{shipment_id}`
- `GET /shipments/{shipment_id}/questions`
- `POST /shipments/{shipment_id}/questions/{question_id}/answer`

Questions are ranked by expected impact on unresolved compliance decisions. The API returns only the highest-value unanswered question.

Phase 6 adds deterministic route scoring and regulation-change impact analysis. The default demo regulation creates a new UAE lithium transit safety-certificate version, identifies affected active or planned shipments, re-runs compliance, and recommends a corrective document upload or alternate compliant route.

Phase 7 adds evidence-grounded HTML/PDF reports, environment-token demo authentication, role checks, request trace IDs, normalized error envelopes, and audit logs for key actions.
