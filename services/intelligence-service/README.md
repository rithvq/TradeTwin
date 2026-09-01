# Intelligence Service

Owns AI-assisted classification prototypes and synthetic risk prediction workflows.

Phase 5 intentionally uses local demo data and a mock LLM provider by default. It does not
claim access to confidential government customs outcomes.

## Endpoints

- `GET /health`
- `POST /intelligence/hs-classify`
- `POST /intelligence/risk-score/{shipment_id}`
- `GET /shipments/{shipment_id}/risk-assessment`

The OpenAI-compatible gateway can be enabled with environment variables, but no API key is required
to run the local demo because `LLM_PROVIDER=mock` is the default.
