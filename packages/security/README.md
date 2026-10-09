# TradeTwin profile security

Install from the repository root with `pip install -e packages/security` before
running domain services locally. Docker installs this package automatically.

The shared middleware validates opaque sessions with the API identity service.
Request context flows into synchronous FastAPI endpoints and downstream HTTP calls.
All domain ORM models inherit `TenantOwned`; queries, relationship loads and bulk
updates/deletes receive an owner filter, and new objects receive the current owner.
Session objects must remain request-scoped. Raw SQL for domain records requires
explicit ownership checks; it must not bypass this ORM layer.

Existing tables receive `owner_id=legacy-unassigned` during the additive startup
migration. No new profile can access that legacy workspace. Profile identities
come from verified provider issuer/subject pairs, never a submitted owner header.

`PROFILE_AUTH_ENABLED=false` is reserved for isolated tests or intentionally public
local demos; it must not be used when storing private documents.
