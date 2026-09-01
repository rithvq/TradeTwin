# Threat Model

This model covers the local project-evaluation prototype.

## Assets

- Shipment, consignment, event, and route data.
- Uploaded documents in MinIO.
- Extracted document metadata.
- Compliance assessments and evidence records.
- Regulation versions and audit logs.
- Demo auth tokens.

## STRIDE Risks

| Risk | Example | Current control | Future hardening |
| --- | --- | --- | --- |
| Spoofing | Calling admin endpoints as another user | Bearer-token demo auth and RBAC | OIDC/SAML, MFA, short-lived tokens |
| Tampering | Editing evidence or regulation versions | Audit logs and append-style records | Immutable ledger, signatures, WORM storage |
| Repudiation | Denying a regulation publish action | Audit log records actor, role, action, resource | External audit sink and signed events |
| Information disclosure | Exposing uploaded trade documents | Local MinIO credentials via env | Per-tenant IAM, encryption, presigned URLs |
| Denial of service | Large file uploads or repeated evaluations | Basic service boundaries | Rate limits, quotas, async workers |
| Elevation of privilege | Viewer publishing a regulation | RBAC role checks | Central policy engine and least privilege |

## Prototype Limits

- Demo tokens are not production authentication.
- Local object storage is not hardened for regulated document retention.
- Audit logs are database records, not an immutable external ledger.
- Rules are demonstration data, not verified legal obligations.
