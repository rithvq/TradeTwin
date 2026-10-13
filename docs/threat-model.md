# Threat Model

## Guarded Dispatch

Phase 4 uses scoped OAuth identities, independent roles, current assignment-bound
packet grants and server-side action/mode/time validation. Decision history has
database immutability guards; movement and token consumption share a transaction.
Source/security changes, revoked permissions, held/conflicting sources and scheduled
rule boundaries fail closed. PAN/FY payloads and document bytes are encrypted;
shared projections filter private evidence and access logs redact query credentials.
See [current controls and residual limits](guarded-dispatch-phase4.md#tests-and-limits).

Registry publishers require trusted provisioning. Database administrators and
authorised applications remain within the trust boundary; encryption and triggers
are not independent WORM attestation. HTTPS, key recovery/rotation, external audit
anchoring, rate limits and production penetration testing remain deployment requirements.

This model covers the local project-evaluation prototype.

Current document protection now includes authenticated file/metadata encryption and
profile isolation. See [confidential document storage](confidential-documents.md) for
the exact coverage, key management, migration risks and remaining deployment controls.
The historical table below describes the earlier prototype baseline.

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
