# Dispatch control on the dashboard

The dashboard now includes a live Dispatch control section below the existing
operational summary. It uses Shipment Service data only. The summary's legacy/demo
fallback values never enter dispatch counts, journey statuses or authorization
checks. No approval or movement command is available from the new section.

## API and access

- `GET /api/v1/dispatch-dashboard?limit=20&cursor=<consignment UUID>`
- `GET /api/v1/consignments/{id}/dispatch-journey?action=PICKUP_CONFIRMED`
- `GET /api/v1/consignments/{id}/dispatch-journey?action=DEPARTED`

Use the existing authenticated session and `X-Organization-Id`. The list filters
candidate trades/assignments by organization, then applies current consignment
access and `compliance.read`, including trade-scoped grants and the assigned
driver restriction. Pagination is stable by creation time and ID; page size is
1–50. Counts cover **all authorized consignments**, not only the current page.
Foreign cursors and journey IDs pass the same access checks. Responses are private,
no-store, including after authenticated middleware and the existing browser proxy.

The projection calls `handoff.readiness`; `READY` is never inferred from a frontend
calculation, an evaluation result alone or a previously issued token. The next
pending action is Pickup before collection, then Departure after collection.
Consignments already moving are shown as historical movement and excluded from
pending-action counts.

| Counter | Meaning |
| --- | --- |
| Ready to move | Existing readiness gate returns `READY` for the pending action |
| Awaiting evidence or review | Gate returns `NOT_ASSESSED`, `EVALUATING`, `ELIGIBLE_FOR_REVIEW` or `NEEDS_REVIEW` |
| Expiring soon | Subset of ready consignments whose authorization expires within five minutes |
| Blocked | Other non-ready outcomes, including stale, expired, unsupported or unusable authorization |

An unknown mandatory requirement can therefore appear blocked: the counter follows
the existing gate rather than weakening its classification. The server's checked
time is shown; each row also retains its own readiness check time.

## Separate Pickup and Departure views with five panels

1. **Evidence changes** shows current/stale/expired evidence, safe change reasons,
   and the existing document, verification, quantity, manifest, assignment and
   corridor indicators. An empty search gaining a match is disclosed only when
   retained baselines prove the transition and the current profile can read a
   matching document. A search match never means reviewed or accepted evidence.
2. **Rule calculation** reuses the existing computation-trace renderer. It shows
   FULL, SHADOW or INCREMENTAL, the authoritative strategy, total/recalculated/
   actually reused counts, safe per-rule reasons and failed/unknown checks. SHADOW
   candidates are labelled eligible for comparison; actual reused results remain
   zero and FULL stays authoritative. A fresh overall evaluation always has its
   own identity; no release permission is carried by a calculation.
3. **Exact binding** shows the evaluation, reviewer approval, packet, driver ACK,
   assignment and manifest separately. Changed bindings cannot be presented as
   current. A 12-character SHA-256 prefix is shown; full hashes and original evidence
   stay behind the existing evidence-manifest API and its current permissions.
4. **Movement** shows **Final check pending** until an actual command, the committed
   event together with its consumed authorization, or a recorded rejection code.
   Existing post-dispatch warnings are separate from the historical decision.
5. **Validity** shows the server-issued valid-from/expires-at window, an informational
   countdown, its limiting input(s), and the immutable issuance inputs. The expiry
   boundary is exclusive. Browser time never grants or consumes permission.

The API retains its seven original stage records as an additive compatibility
projection; the user interface groups them into the five panels above. List rows
also expose next action, current stage, reasons, expiry and their own checked time.

Historical journeys follow the authorization actually consumed by their event and
its exact evaluation, rather than silently substituting a later evaluation. They
are labelled historical and confer no current permission. Pickup and Departure
are queried independently and cannot share an evaluation or authorization through
this UI.

The existing gate does not automatically revoke an earlier authorization merely
because a new evaluation with unchanged dependencies is requested. This behavior
is preserved: the dashboard names the authorization's own evaluation and explicitly
marks its release chain as different from the newer evaluation. The newer evaluation
still needs its own independent approval, packet, ACK and authorization. Readiness
always reports what the existing movement validator actually accepts.

Imported legacy movements without a consumed authorization show the event as
recorded and the guarded check as **not recorded**, never as a fabricated pass.

## Ownership and consistency

The new projection lives in `compliance/dashboard.py`, with small stage builders
in `dashboard_stages.py` and typed public schemas in `schemas_dashboard.py`.
Existing readiness, evaluation, packet, authorization and event records remain
authoritative. The movement validator, locks, consumption and max/min validity
calculation are unchanged.

Additive migration **trade_009** adds two immutable explanation tables:

- `compliance_evidence_change_baselines` retains redacted query counts/digests,
  component/engine fingerprints and provable empty-to-nonempty transitions between
  evaluations. It contains no raw query witnesses or verification payloads. Public
  responses expose only safe codes and permission-filtered transition labels.
- `dispatch_authorization_windows` records the exact start/expiry inputs used at
  issuance and all tied limiting inputs. Evaluation evidence deadlines come from
  the frozen evaluation, not later mutable sources. The evaluation-validity input
  remains an aggregate boundary when a more specific cause was not recorded.

Database triggers reject changes/deletions in both tables. Their content hashes
are checked before public projection. Startup applies the normal migration chain;
existing business rows are preserved, with no historical backfill. Older records
show **Detail not recorded.** rather than inferring reasons from today's evidence.

The list takes the existing registry-before-trade locks for each consignment
inside a read-only savepoint, then rolls it back before visiting another trade.
This keeps each row's projection consistent without retaining exclusive trade
locks across an organization-wide scan. The response is a series of checked
snapshots, not a promise that nothing can change after transmission. Authorization
consumption still validates current conditions atomically with movement recording.
See [PostgreSQL's row-lock/savepoint semantics](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS).

Failed commands previously rolled back without a retained attempt observation.
`operations/movement_attempts.py` now adds only an existing audit event after that
rollback, rechecking the current driver's authority in a separate transaction.
It stores action, client event ID and rejection code, never the submitted payload,
private evidence or dependency witnesses. Audit failure cannot change the original
error or permit movement. Anonymous/unauthorized attempts do not gain an audit
write through this path. Malformed requests rejected before command execution are
not represented as completed movement checks.

Links lead to the existing compliance/dispatch desk or current driver's task,
according to current read/action capabilities. Desk deep links select the requested
consignment and Pickup/Departure tab. All actual commands retain their original
role checks, independent review, packet, acknowledgment and idempotency rules.

## Refresh and unavailable state

The list refreshes every 30 seconds; an open journey refreshes every 10 seconds.
Successful existing operational mutations signal immediate refresh in the same
tab and other tabs using a data-free local-storage notification. Movement errors
also refresh the observation. Focus and manual refresh recheck the server.

Requests are bounded to 20 seconds, superseded requests are cancelled, and timer
polling does not accumulate overlapping requests. A failed or timed-out refresh
clears the corresponding old projection and shows **Current status unavailable**.
Organization changes clear old rows immediately, including during slow requests.
An expiry timer requests a fresh server result; it never grants permission locally.

Counts deliberately validate every visible consignment. Very large organizations
may require further batching/indexed projection work; this increment does not
replace live validation with an authorization cache to make counting cheaper.

## Verification

- Focused dashboard acceptance: organization/driver/grant isolation, safe metadata,
  separate journeys, vehicle change, expiry, quantity-rejection rollback followed
  by success, pagination/global counts and FULL-versus-SHADOW reporting.
- PostgreSQL dashboard/migration acceptance: 17 passed, including duplicate movement attempts.
  The two existing PostgreSQL consumption tests also passed for repeated and
  distinct concurrent commands, with one logical movement effect.
- Relevant dispatch/migration/selective-calculation regression: 94 passed, four
  PostgreSQL-only checks skipped in the SQLite run. The expanded dashboard suite
  and authenticated cache/organization checks also passed locally.
- Frontend: 90 tests passed; lint, typecheck, formatting, architecture and production
  build passed. Coverage includes 30/10-second polling, immediate refresh, failed
  and hung refreshes, organization switching and incremental-only reuse display.
- Guarded-dispatch OpenAPI, public schemas and Postman collection include the new
  read endpoints. Existing paths and schemas have no semantic changes.

The authenticated browser check additionally opens both journeys on the dashboard,
checks desktop/mobile overflow and follows the deep link back to the existing
compliance desk. It runs with disposable services and synthetic encrypted files;
screenshots are retained under `artifacts/audit/dispatch/`.
