# TradeTwin Architecture

## Phase 7 Scope

Phase 7 prepares TradeTwin for project evaluation with compliance report export, demo authentication and RBAC, audit logs, API documentation, Docker deployment documentation, a threat model, a legal disclaimer, and a guided walkthrough. It intentionally does not implement production OCR, live LLM extraction, real customs filing, or real customs rules.

## Application Boundary

### Web App

The Next.js application will become the operator-facing interface for shipment timelines, compliance status, document workflows, alerts, and simulations.

### API

The API is the initial public backend entry point. It will eventually coordinate requests from the web app and route work to domain services. In Phase 0 it only exposes a health endpoint and contains backend tooling for settings, SQLAlchemy, Alembic, pytest, and Ruff.

## Future Service Boundaries

### Shipment Service

Owns shipment lifecycle state, consignments, route legs, milestones, and logistics events. In Phase 1 it persists shipment data in PostgreSQL and projects shipment relationships into Neo4j.

The graph projection models:

- Shipment contains Consignment
- Shipment has RouteLeg
- Consignment originates in Country
- Consignment is destined for Country
- ShipmentEvent affects Shipment or Consignment
- ShipmentEvent occurred in Country

Phase 1 event handling is limited to shipment state projection. For the seeded India to UAE to Germany route, an unloading event in UAE marks the UAE-bound consignment as `UAE_IMPORT` while the Germany-bound consignment remains `UAE_TRANSIT`.

### Compliance Service

Owns deterministic compliance checks, versioned demo rules, assessment persistence, corrective-action recommendations, consistency checks, information-gain questions, route optimization, regulatory change impact analysis, reports, demo RBAC, and audit logs. Phase 2 stores assessment results in PostgreSQL, records job state in Redis when available, and evaluates rules from JSON files. Phase 3 can pull extracted document metadata from the Document Service and emits evidence records after each assessment. Phase 4 detects conflicts across documents, shipment state, route legs, and events, then asks only the highest-impact unresolved question first. Phase 6 allows draft regulation versions to be created and published, compares shipment status before and after a triggering rule, persists the new assessment, and recommends corrective document upload or an alternate compliant route. Phase 7 exports evidence-grounded HTML/PDF reports and records key user actions in audit logs.

The demo rule engine supports India, UAE, and Germany. For the India to UAE to Germany scenario, UAE import rules apply to consumer electronics unloaded in UAE, while UAE transit rules apply to lithium batteries that continue onward to Germany.

Route optimization remains deterministic. It compares the current route with seeded alternates, considers required documents, estimated duty, demo FTA eligibility, synthetic risk score, and delay, then rejects legally invalid options before selecting the best compliant route.

### Document Service

Owns document metadata, MinIO object storage references, basic PDF/text extraction workflow state, verification status, and the evidence provenance ledger. Phase 3 stores evidence records that connect an assessment to a rule, regulation version, supporting or missing document, and relevant shipment event.

### Intelligence Service

Owns AI-assisted analysis and prediction prototypes. Phase 5 includes a mock-first LLM gateway, an OpenAI-compatible gateway interface, seeded HS-code taxonomy matching, and scikit-learn risk models trained only from synthetic demo outcomes. The service does not claim access to confidential government customs outcomes.

## Shared Packages

### packages/shared

Reserved for cross-service primitives that are stable and non-domain-specific, such as common response shapes or observability helpers.

### packages/domain

Reserved for shared domain vocabulary and schemas that must be consistent across services. Shared domain code should remain small to keep service ownership clear.

## Infrastructure

### PostgreSQL with pgvector

Primary relational store and future vector-capable persistence layer.

### Neo4j

Future graph store for trade networks, regulatory relationships, parties, products, and jurisdiction links.

### Redis

Future cache, queue, and coordination layer.

### MinIO

S3-compatible object storage for uploaded trade documents and generated artifacts.
