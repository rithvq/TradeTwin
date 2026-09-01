# Document Service

Owns document uploads, MinIO object references, basic PDF/text extraction, and the Phase 3
evidence provenance ledger.

## Endpoints

- `GET /health`
- `POST /shipments/{id}/documents`
- `GET /shipments/{id}/documents`
- `POST /documents/{id}/extract`
- `GET /documents/{id}`
- `POST /assessments/{id}/evidence`
- `GET /assessments/{id}/evidence`

Supported demo document types are commercial invoice, packing list, certificate of origin,
safety certificate, and transit declaration. Extraction is deterministic and limited to embedded
PDF text or plain text content; advanced OCR and LLM extraction are intentionally out of scope.
