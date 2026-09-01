# Architecture Diagram

```mermaid
flowchart LR
  Web[Next.js Web Console] --> Shipment[Shipment Service]
  Web --> Compliance[Compliance Service]
  Web --> Document[Document Service]
  Web --> Intelligence[Intelligence Service]

  Shipment --> Postgres[(PostgreSQL + pgvector)]
  Shipment --> Neo4j[(Neo4j Shipment Graph)]

  Compliance --> Postgres
  Compliance --> Redis[(Redis Job State)]
  Compliance --> Shipment
  Compliance --> Document

  Document --> Postgres
  Document --> MinIO[(MinIO Object Storage)]

  Intelligence --> Postgres
  Intelligence --> Shipment
  Intelligence --> Taxonomy[Seeded HS Taxonomy]
  Intelligence --> Synthetic[Seeded Synthetic Outcomes]

  Compliance --> Rules[Versioned Demo Rules]
  Compliance --> Reports[HTML/PDF Reports]
  Compliance --> Audit[Audit Logs]
```

## Boundary Summary

- Shipment Service owns shipment lifecycle, events, route legs, and graph projection.
- Compliance Service owns deterministic rule evaluation, route optimization, reports,
  regulation impact analysis, RBAC, and audit logs.
- Document Service owns MinIO uploads, extraction metadata, and evidence records.
- Intelligence Service owns mock-first HS recommendations and synthetic risk scoring.
