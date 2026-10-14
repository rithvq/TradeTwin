# Phase 7 Operator Runbooks

This prototype remains unqualified. Owners below are explicit capability roles, not
automatic escalation contacts. Assign named on-call principals before any pilot.
No runbook authorises manual bypass of business guards, clearance or bank settlement.

| Trigger | Owner | Immediate Action | Evidence To Preserve | Validation And Escalation |
| --- | --- | --- | --- | --- |
| Source outage/stale coverage | Corridor source steward | Retain outage; block uncertain routes; never interpret silence as reopening | Fetch/error and coverage references | Check freshness/reviewed policy; escalate to operational reviewer |
| Suspected source conflict/retraction | Corridor reviewer | Preserve both reports/tombstone; request independent review | Source/event revisions and affected scope epochs | Reassess current route; escalate unresolved contradictions |
| Adverse observation after departure | Compliance reviewer | Raise factual incident and operational protection; do not rewrite original decision | Original evaluation/authorisation and new observation | Check current facts/proof; escalate to transport coordinator |
| Protected recovery/moving vehicle | Carrier dispatcher | Record incident and actual driver response; do not claim a physical stop or resume | Reported motion time, case/assessment references | Recovery execution is unavailable: escalate, not override |
| Driver cannot stop safely | Carrier dispatcher | Preserve factual response and seek safe external operational direction | Response/assignment/location timestamps | Never demand unsafe stopping through application approval |
| Document quarantine/parser limits | Document reviewer | Keep bytes quarantined; do not approve metadata from failed extraction | Asset hash/security state and redacted job code | Resubmit safe source through normal desk; escalate repeated failure |
| Wrong vehicle/expired authority proof | Compliance reviewer | Reject applicability; obtain correct current evidence and new review | Reviewed document/version/binding/observation references | Reevaluate and issue a new action-bound packet only after gates pass |
| Approval/grant revocation or stale token | Organisation administrator | Revoke through normal membership controls; retain history | Grant/approval/token IDs and immutable event references | Verify every new read/worker/consume denies obsolete authority |
| Queue outage/stale worker | Deployment operator | Preserve DB outbox/attempts; restore queue, never publish an old lease | Job, lease expiry, attempts and redacted error code | Run authorised retry and verify unique result publication |
| Binding or movement incident | Deployment operator | Pause with exact deployment ETag and reason | Pause event, controls version, original unused token/evaluation | Verify new bindings/permissions denied; factual reporting preserved |
| Data restore/integrity incident | Deployment operator | Pause, preserve independent fence, rotate generation, restore business set only | Backup age, generation IDs, lost-window/outbox evidence | Full reconciliation/reactivation is unavailable; remain protected and escalate |
| Export/privacy/performance incident | Evidence analyst + deployment operator | Revoke access, expire affected bundles; retain safe telemetry only | Recipient/resource IDs, job/error codes, measured topology | Recheck current permissions/redaction; do not claim unmeasured scale targets |

## Restore Boundaries

Back up database, encrypted object storage and required keys under separately controlled
policies. Do not include the independent operational generation in the business restore
set. Test key availability without logging keys or decrypted documents. Preserve historical
proof that a consumed permission was valid at the time, even if current evidence is adverse.

The registered `ISOLATED_SQLITE_FENCE_V1` exercise proves only marker restoration and a
detected post-backup gap in an in-memory test. It does not back up PostgreSQL/MinIO,
measure production RPO/RTO, recover missing business history or activate a deployment.
Never invent events to fill the lost interval. Reconcile factual external observations,
idempotency keys, booking reservations, queues and object references through their owning
modules, then run deployment-specific assurance and independent review.
