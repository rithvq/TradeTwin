# Selective compliance measurements

Measured on 26 October 2026 with synthetic domestic demo data, Python 3.12.6, PostgreSQL 16 in Docker and SQLite on Windows. Three warm iterations per mode followed a priming full evaluation. Other validation processes shared the workstation, so these small samples do not establish a speedup or production capacity. CPU measurements use the host process clock and have coarse resolution.

Both captures use engine code hash `11f5706f147e9ac2bee0d6cee4b3ab9e5c72c6eddf3385718377b7be7ea458d4`. [SQLite raw samples](benchmarks/selective-compliance-sqlite.json) and [PostgreSQL raw samples](benchmarks/selective-compliance-postgresql.json) retain the complete engine manifest and measurements. No business documents, credentials or source values are in these artifacts.

All figures below are medians. Planning includes dependency compilation/digests, lookup and witness validation as well as rule execution. Global checks and aggregate assembly always run. The transaction window starts after the registry lock is acquired and ends after commit; it includes the request, trade lock, preparation, execution and persistence, but excludes queueing and HTTP latency. Lock wait is retained separately in the raw files. These are uncontended synthetic transactions, not a production lock-contention benchmark.

| Database | Mode | Rule executions | Planning CPU ms | Planning wall ms | Transaction window ms |
| --- | --- | ---: | ---: | ---: | ---: |
| sqlite | FULL | 17 | 15.6 | 16.0 | 201.5 |
| sqlite | SHADOW | 17 | 62.5 | 59.1 | 264.6 |
| sqlite | INCREMENTAL | 0 | 46.9 | 45.4 | 204.4 |
| postgresql | FULL | 17 | 31.3 | 36.1 | 893.5 |
| postgresql | SHADOW | 17 | 78.1 | 148.3 | 963.5 |
| postgresql | INCREMENTAL | 0 | 78.1 | 111.0 | 652.3 |

Snapshot preparation is measured separately and remains fully executed for every evaluation:

| Database | Mode | Preparation wall ms | Preparation CPU ms | SQL: preparation / planning / persistence | Persistence wall ms |
| --- | --- | ---: | ---: | --- | ---: |
| sqlite | FULL | 75.1 | 78.1 | 252 / 17 / 76 | 55.6 |
| sqlite | SHADOW | 76.7 | 62.5 | 252 / 51 / 76 | 62.4 |
| sqlite | INCREMENTAL | 75.7 | 78.1 | 252 / 51 / 26 | 20.3 |
| postgresql | FULL | 434.3 | 156.3 | 252 / 17 / 76 | 172.4 |
| postgresql | SHADOW | 412.8 | 187.5 | 252 / 51 / 76 | 187.9 |
| postgresql | INCREMENTAL | 310.8 | 125.0 | 252 / 51 / 26 | 62.3 |

Additional retained JSON per evaluation (both database fixtures have the same record shape):

| Mode | New calculation records | New witnesses | Additional JSON KiB |
| --- | ---: | ---: | ---: |
| FULL | 17 | 326 | 301.2 |
| SHADOW | 17 | 326 | 301.2 |
| INCREMENTAL | 0 | 0 | 225.3 |

JSON bytes include the encrypted capture envelope and new kernel/reference/witness JSON. They exclude indexes, row overhead, computation links/specification metadata, existing evaluation/requirement history and backups. This is added retained content, not total database disk usage. FULL here includes the new retention work; the pre-change evaluator without it was not benchmarked.

Reuse eliminated 17 rule executions in the unchanged-input fixture, but added dependency validation work and SQL reads. Reduced persistence can offset some of that overhead, particularly on PostgreSQL, while snapshot preparation still dominates. These samples do not justify automatic activation. Default mode remains FULL; use SHADOW with representative workloads before opting into INCREMENTAL.

Reproduce with `pytest services/shipment-service/tests/test_selective_compliance.py -k benchmark`. Set `TRADE_TEST_DATABASE_URL` only to a disposable PostgreSQL database to obtain PostgreSQL measurements; fixtures create and remove a random schema.

Verification of this increment:

- Complete API/service regression: **342 passed, 15 skipped** (optional PostgreSQL cases in the SQLite invocation).
- Focused PostgreSQL calculation, replay, epoch-race and migration suite: **24 passed**.
- Additional PostgreSQL duplicate-consumption, epoch-race, migration and benchmark invocation in INCREMENTAL mode: **6 passed**.
- Frontend: **81 tests passed**; lint, typecheck, formatting, architecture and production build passed.
- Authenticated browser flow in INCREMENTAL mode: trace/no-store checks, desktop/mobile explanation, independent release review, encrypted packet download, driver acknowledgment and separate pickup/departure permissions passed.
- Postman CLI read-only collection passed locally with run reporting disabled and disposable credentials.
- Contract-schema tests: **3 passed**; guarded-dispatch OpenAPI/schema/collection regenerated. Other phase exports produced no contract changes.

The earlier SQLite reflection failure was fixed by inspecting the existing session connection, avoiding a second connection during a large write transaction. The previously failing freight handoff test and the full suite then passed. No business semantics or authorization checks were relaxed.
