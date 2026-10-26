# Selective compliance calculation

TradeTwin keeps its full guarded-dispatch evaluator as the reference. The additive
`trade_008` migration introduces consignment-local calculation evidence. It does
not introduce another ledger, rule language, or dispatch permission service.

## Server control and rollout

`COMPLIANCE_EVALUATION_MODE=FULL` is the default in `.env.example`. Set the same
server environment in the shipment service and document worker, then recreate
those containers when changing it. No browser form can select this setting.

| Mode | Calculation | Authoritative result |
| --- | --- | --- |
| FULL | Execute every rule and retain its dependency basis | Full evaluator |
| SHADOW | Execute full evaluation and independently plan validated selective reuse; compare complete semantic outputs | Full evaluator, even on mismatch |
| INCREMENTAL | Validate each compatible computation, otherwise calculate that rule | New evaluation with current global checks and aggregate |

Keep FULL for normal deployments. First collect representative SHADOW comparisons
with no unexplained mismatches, run PostgreSQL races and measure the actual workload.
Incremental mode is opt-in; passing the synthetic tests is not production
qualification. Revert the server setting to FULL if results or latency regress.
Already queued evaluations use the server mode at completion. Previously issued
permissions continue to use their original, unchanged consumption guards.

## Calculation boundary

`preparation.prepare_snapshot` reads the database and captures one trusted assessment
time, current registry, facts, exact document bindings, observations, deadlines,
scope/query revisions and global safety state. It performs the existing whole-context
fingerprint check before calculating. Input providers still run afresh; this phase
does not cache document parsing, government lookups or provider normalization.

`calculation.calculate_full` has no database, network, clock or business writes.
It preserves three-valued applicability, all four date bases, evidence outcomes,
unsupported scope, source conflicts, recipient checks and deadline aggregation.
`evaluations.persist_evaluation` writes fresh requirement IDs and an evaluation hash.
The initial separation passed the pre-cache guarded regression milestone (57 passed,
2 PostgreSQL-only checks skipped).

Cached kernels contain rule arithmetic and diagnostics. Requirement wrappers are
assembled afresh, including current evidence references and ACTION_TIME timestamps.
All global checks and aggregate decisions are recalculated, even when every kernel
can be reused. A current hold or blocked corridor therefore still blocks release.

## Dependency design

The compiler walks both applicability and satisfaction expressions, including all
branches, rather than trusting declared `dependency_paths`. Explicit provider
closures cover invoice/turnover facts, verification, assignment, transport, loading,
binding, invoice reservation and the supported-scope calculation. Unknown providers
or unregistered diagnostics make a rule non-reusable. No inference of independence
is made from an unfamiliar derived input.

Each basis pins the trade, consignment, action, SIMULATION/PRODUCTION mode, immutable
rule/pack and current registry, compiler/provider/code and runtime manifest, source
hashes/revisions, query matches and scope epochs. Reuse requires matching integrity
hashes and witnesses, complete coverage and a half-open trusted-time interval:
`valid_from <= assessment_time < valid_until`. Deadlines are conservatively bounded
by the full evaluation's earliest deadline, including rule effectivity and evidence
expiry. This can invalidate more rules than necessary, which is intentional.

Evidence queries retain even an empty match list. Queries currently cover all
documents of a type within the trade, while computations remain consignment-local.
This conservative scope can trigger extra recalculation across consignments; it
does not permit cross-consignment reuse. Query membership includes unreviewed
uploads, but acceptance still comes solely from existing submitted review and exact
binding providers. An upload can invalidate absence without satisfying a rule.

`RuleDependencySpecification`, `RuleComputation`, `DependencyWitness`,
`EvaluationComputationLink` and `EvaluationExecution` are immutable. Only the current
`DependencyScopeEpoch` rows are mutable. Missing epochs force fresh calculation;
new random generation IDs prevent a deleted/recreated epoch from matching old
history at the same counter. Reads refresh ORM epoch values after database triggers.

## Invalidation and consistency protocol

1. Existing command transactions acquire registry locks before trade/resource locks.
2. Business changes and dependency revisions commit or roll back together. Audit
   adapters cover normal mutation paths; database triggers also cover document heads,
   type/trade moves, attachment integrity/security, assignments, vehicles, accepted
   terms, consignment plans, fact/binding/loading heads, transport reviews and
   verification/connection/key changes. Updates with unchanged watched fields do
   not advance epochs. Moves advance old and new scopes.
3. Rule publication/suspension and conflict resolution retain the registry's existing
   epoch/manifest. Corridor intelligence retains its existing scoped epochs and
   current projection hash. These are freshly resolved, not replaced by Redis events.
4. The worker holds the existing lock scope while preparing, validating reuse and
   retaining the new evaluation. Specification registration uses conflict-safe insertion.
5. Issuance and pickup/departure consumption still validate exact current context,
   registry, assignment, evidence, trusted time, movement, manifest, grant and
   corridor conditions. Atomic authorization consumption and event insertion remain
   in the existing transaction. Repeated commands retain one logical movement effect.

No calculation reuse carries release approval, packet preparation, driver
acknowledgment or dispatch authorization into the new evaluation. Whole-context
validation remains the outer safety guard. Direct database maintenance must retain
application locking conventions; triggers are not a replacement for those locks.

## Explanation, confidentiality and replay

`GET /api/v1/compliance-evaluations/{id}/computation-trace` applies current
`compliance.read` access and declares `Cache-Control: private, no-store`; the profile
middleware enforces a final `no-store` response. It exposes
strategy/counts, rule dispositions and reason codes. It exposes no query rows,
private document values, encrypted captures or dependency witnesses. Pre-migration
or unfinished evaluations explicitly return `NOT_RECORDED`. The evaluation desk
has a read-only “How checks were calculated” panel with the release-workflow notice.

Captured calculation inputs/results are sealed with the existing AES-GCM document
key ring and entity/organisation-bound authenticated data. Retain historical keys
when rotating; do not put key contents in reports or logs. Captures increase storage
and must follow the deployment's confidential-record retention/backup controls.

DISPATCH_AUTHORISATION replay can recompute these retained inputs only with the
exact registered code/runtime/provider manifest and original assessment time. A
legacy capture is incomplete, and a different engine is explicitly unsupported.
Input/result hashes are checked before replay. Difference values are withheld;
only paths/reasons are retained for compliance recomputation. Existing replay
permissions, read-time recipient checks and filtered decision comparisons remain.
Historical replay creates no current readiness or permission.

## Reproducible verification and measurements

Run `pytest services/shipment-service/tests/test_selective_compliance.py services/shipment-service/tests/test_computation_certificates.py` for pure/full
equivalence, shadow authority, reused/new identities, absence, unreviewed uploads,
epoch loss, canonical/mapping witnesses, temporal boundaries, immutability, privacy,
stale workers, independent dependencies and current global blocks. The release-chain
regression starts with an existing authorisation, reuses its rule computations in a
new evaluation, rejects its approval, packet and acknowledgment against that new
evaluation, and issues a separate authorisation after a fresh release workflow.
Certificate tests exercise the real validator with altered specifications, witnesses,
results, references and intervals, plus partition/version mismatches. They check
half-open validity and rule effectivity for all four date bases. Set
`TRADE_TEST_DATABASE_URL` to a **disposable PostgreSQL** database to exercise row-lock
races; each fixture creates and removes a random schema. CI includes this suite in
its PostgreSQL job. Existing dispatch concurrency tests also run with
`COMPLIANCE_EVALUATION_MODE=INCREMENTAL` to check duplicate token consumption.

The benchmark test produces ignored, synthetic-only JSON artifacts in
`artifacts/audit/selective-compliance-benchmark-{sqlite,postgresql}.json`. It records
the engine manifest, rule executions, SQL statement counts, CPU/wall time, preparation
separately, persistence time, registry-lock wait, transaction lock window, and newly
retained JSON bytes/computation/witness counts. Storage numbers exclude indexes,
row overhead, links/specification metadata and backups; they are not disk-size claims.
Lock windows include request preparation, SQL and persistence; they are not measured
with production contention. Three warm samples per mode are exploratory, not a
capacity assessment. See [measurements](selective-compliance-benchmarks.md).

## Prior-art investigation notes

These comparisons identify related published mechanisms and questions to investigate.
They establish no novelty or patentability and are not an exhaustive patent search.

| Primary source | Existing mechanism | TradeTwin investigation focus (inference) |
| --- | --- | --- |
| [Adapton, PLDI 2014](https://matthewhammer.org/adapton/) | Demand-driven incremental computation with dependency graphs and separation of computations from observers | Application-specific negative evidence queries, immutable bounded rule results and the separately validated dispatch workflow |
| [PostgreSQL 16 isolation documentation](https://www.postgresql.org/docs/16/transaction-iso.html) | Transaction isolation, phantom reads and serializable predicate conflict tracking | Explicit persistent evidence-scope epochs supplement application locks; this implementation does not claim to be SSI or a general substitute for serializable transactions |
| [Zanzibar, USENIX ATC 2019](https://www.usenix.org/conference/atc19/presentation/pang) | Authorization consistency across changes to access controls and object contents | Distinguishing cached factual calculations from one-use, action-bound dispatch permission and validating consistency again at consumption |

Retain this protocol, captured engine manifests, test race demonstrations and raw
synthetic benchmarks when investigating the interaction between absence tracking,
time-bounded result reuse and dispatch-time consistency validation.
