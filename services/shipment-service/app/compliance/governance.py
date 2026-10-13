"""Source-backed immutable rules, independent exact-hash publication and registry epochs."""

from sqlalchemy import select

from app.operations.access import exists, fail
from app.operations.models import Attachment
from app.trades.access import require
from app.trades.context_locks import registry_lock
from app.trades.terms import digest

from . import suites
from .clock import aware, instant
from .ledger import independent, record, view
from .models import Pack, Publication, Registry, Rule, Source, SourceConflict, TestRun


def source(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.source.register")
    attachment = exists(db, Attachment, payload.snapshot_attachment_id)
    if attachment.uploaded_by_organization_id != ctx.org_id:
        fail("NOT_FOUND", "Source snapshot not found in this organisation.", status=404)
    from app.document_desk.models import Asset
    from app.operations.models import AttachmentLink

    if (
        attachment.purpose != "OTHER"
        or db.scalar(select(Asset.id).where(Asset.attachment_id == attachment.id))
        or db.scalar(select(AttachmentLink.id).where(AttachmentLink.attachment_id == attachment.id))
    ):
        fail(
            "FORBIDDEN",
            "Use a dedicated public regulation snapshot, not business evidence.",
            status=403,
        )
    if attachment.security_state != "CLEAN" or attachment.sha256 != payload.source_sha256:
        fail(
            "SOURCE_SNAPSHOT_INVALID",
            "Upload/scan the exact source snapshot; the server hash must match.",
        )
    if payload.retrieved_at > instant(db):
        fail("VALIDATION_ERROR", "Source retrieval cannot be in the future.", status=422)
    if payload.supersedes_source_id:
        exists(db, Source, payload.supersedes_source_id)
    data = payload.model_dump(mode="json")
    row = Source(
        source_kind=payload.source_kind,
        issuer=payload.issuer,
        title=payload.title,
        official_url=payload.official_url,
        snapshot_attachment_id=str(payload.snapshot_attachment_id),
        source_sha256=payload.source_sha256,
        source_json=data,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "REGULATION_SOURCE_REGISTERED", row, summary={"source_hash": row.source_sha256})
    return {**view(row), "conflict_status": "NONE"}


def create_pack(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.pack.prepare")
    if payload.family_code != suites.FAMILY:
        fail(
            "UNSUPPORTED_SCOPE",
            "Only the initial India ordinary-road rule family can enable dispatch.",
            status=422,
        )
    for source_id in payload.source_ids:
        exists(db, Source, source_id)
    data = payload.model_dump(mode="json", by_alias=True)
    rule_data = data.pop("rules")
    row = Pack(
        family_code=payload.family_code,
        version=payload.version,
        environment=payload.environment,
        title=payload.title,
        input_schema_version=payload.input_schema_version,
        rule_schema_version=payload.rule_schema_version,
        supported_scope_json=payload.supported_scope_predicate,
        excluded_scope_json=payload.excluded_scope_predicate,
        coverage_json=payload.coverage_dimensions,
        policy_json=data,
        source_ids=data["source_ids"],
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        limitations_json=payload.limitations,
        content_hash=digest({**data, "rules": rule_data}),
        test_suite_hash=suites.SUITE_HASH,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    db.flush()
    for definition in rule_data:
        db.add(
            Rule(
                pack_revision_id=row.id,
                rule_code=definition["rule_code"],
                rule_version=definition["rule_version"],
                requirement_code=definition["requirement_code"],
                rule_class=definition["class"],
                rule_json=definition,
                content_hash=digest(definition),
                created_by_user_id=ctx.user.id,
            )
        )
    record(
        db,
        ctx,
        "RULE_PACK_DRAFT_CREATED",
        row,
        summary={"pack_hash": row.content_hash, "environment": row.environment},
    )
    return pack_view(db, row)


def definition(db, pack):
    rules = [
        r.rule_json
        for r in db.scalars(
            select(Rule).where(Rule.pack_revision_id == pack.id).order_by(Rule.rule_code)
        )
    ]
    return {**pack.policy_json, "rules": rules}


def check_hash(row, claimed):
    if row.content_hash != claimed:
        fail(
            "EVALUATION_STALE",
            "Review/test/publication must bind the exact immutable pack hash.",
            status=412,
        )


def test_pack(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.pack.test")
    pack = exists(db, Pack, ident)
    check_hash(pack, payload.pack_hash)
    output = suites.run(definition(db, pack))
    row = TestRun(
        pack_revision_id=pack.id,
        pack_hash=pack.content_hash,
        suite_hash=suites.SUITE_HASH,
        status="PASSED" if output["passed"] else "FAILED",
        results_json=output,
        engine_version=suites.ENGINE_VERSION,
        completed_at=instant(db),
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(
        db,
        ctx,
        "RULE_PACK_TESTED",
        row,
        summary={"status": row.status, "pack_hash": pack.content_hash},
    )
    return view(row)


def review_pack(db, ctx, ident, payload):
    require(db, ctx.user, ctx.org_id, "regulation.pack.review")
    pack = exists(db, Pack, ident)
    independent(ctx, pack.created_by_user_id)
    check_hash(pack, payload.pack_hash)
    test = exists(db, TestRun, payload.passed_test_run_id)
    if (
        test.pack_revision_id != pack.id
        or test.pack_hash != pack.content_hash
        or test.suite_hash != suites.SUITE_HASH
        or test.status != "PASSED"
    ):
        fail(
            "PACK_TESTS_NOT_PASSED", "The required registered tests must pass for this exact pack."
        )
    sources_current(db, pack, True)
    row = Publication(
        pack_revision_id=pack.id,
        event_type="REVIEW_APPROVED",
        pack_hash=pack.content_hash,
        test_run_id=test.id,
        reason=payload.reason,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "RULE_PACK_REVIEW_APPROVED", row)
    return view(row)


def registry(db, environment, create=False):
    key = (suites.FAMILY, environment, "INDIA")
    row = db.get(Registry, key)
    if row is None and create:
        row = Registry(
            family_code=suites.FAMILY,
            environment=environment,
            jurisdiction_key="INDIA",
            registry_epoch=0,
            publication_manifest_json={"published": [], "suspended": []},
            updated_at=instant(db),
        )
        db.add(row)
        db.flush()
    return row


def publish(db, ctx, ident, payload):
    registry_lock(db, True)
    require(db, ctx.user, ctx.org_id, "regulation.pack.publish")
    pack = exists(db, Pack, ident)
    independent(ctx, pack.created_by_user_id)
    check_hash(pack, payload.pack_hash)
    approval = exists(db, Publication, payload.review_approval_event_id)
    if (
        approval.event_type != "REVIEW_APPROVED"
        or approval.pack_revision_id != pack.id
        or approval.pack_hash != pack.content_hash
        or approval.created_by_user_id == pack.created_by_user_id
    ):
        fail("SELF_REVIEW_NOT_ALLOWED", "Publish the exact independently approved pack.")
    test = exists(db, TestRun, approval.test_run_id)
    if test.status != "PASSED" or test.suite_hash != suites.SUITE_HASH:
        fail("PACK_TESTS_NOT_PASSED", "Registered test suite changed or did not pass.")
    sources_current(db, pack, True)
    head = registry(db, pack.environment, True)
    content = dict(head.publication_manifest_json)
    if pack.id in content["published"]:
        fail("PACK_ALREADY_PUBLISHED", "Immutable pack is already published.")
    content["published"] = [*content["published"], pack.id]
    head.publication_manifest_json = content
    head.registry_epoch += 1
    head.updated_at = instant(db)
    row = Publication(
        pack_revision_id=pack.id,
        event_type="PUBLISHED",
        pack_hash=pack.content_hash,
        test_run_id=test.id,
        reason="Exact tested and independently reviewed publication",
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "RULE_PACK_PUBLISHED", row, summary={"registry_epoch": head.registry_epoch})
    return {**view(row), "registry_epoch": head.registry_epoch}


def suspend(db, ctx, ident, payload):
    registry_lock(db, True)
    require(db, ctx.user, ctx.org_id, "regulation.pack.suspend")
    pack = exists(db, Pack, ident)
    head = registry(db, pack.environment)
    if not head or pack.id not in head.publication_manifest_json["published"]:
        fail("PACK_NOT_PUBLISHED", "Only a published pack can be suspended.")
    content = dict(head.publication_manifest_json)
    content["suspended"] = sorted(set(content["suspended"]) | {pack.id})
    head.publication_manifest_json = content
    head.registry_epoch += 1
    head.updated_at = instant(db)
    row = Publication(
        pack_revision_id=pack.id,
        event_type="SUSPENDED",
        pack_hash=pack.content_hash,
        reason=payload.reason,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "RULE_PACK_SUSPENDED", row)
    return view(row)


def conflicts(db, pack):
    return [
        c
        for c in db.scalars(select(SourceConflict).where(SourceConflict.status == "OPEN"))
        if set(c.source_ids) & set(pack.source_ids)
    ]


def sources_current(db, pack, strict=False):
    states = []
    for source_id in pack.source_ids:
        source = exists(db, Source, source_id)
        if (
            strict
            and pack.environment == "PRODUCTION"
            and source.source_json.get("source_origin") == "SIMULATION_FIXTURE"
        ):
            fail(
                "UNSUPPORTED_SCOPE", "Production publication cannot use synthetic source snapshots."
            )
        attachment = exists(db, Attachment, source.snapshot_attachment_id)
        states.append(
            {
                "id": source.id,
                "source_hash": source.source_sha256,
                "source_status": source.source_json.get("source_status", "UNKNOWN"),
                "clean": attachment.security_state == "CLEAN"
                and attachment.sha256 == source.source_sha256
                and source.source_json.get("source_status") == "ACTIVE",
            }
        )
    unresolved = conflicts(db, pack)
    superseded = [
        c.id
        for c in db.scalars(select(SourceConflict).where(SourceConflict.status == "RESOLVED"))
        if set(c.source_ids) & set(pack.source_ids)
        and set(pack.source_ids)
        & (set(c.source_ids) - set(c.resolution_json.get("governing_source_ids", [])))
    ]
    if strict and (unresolved or superseded or not all(s["clean"] for s in states)):
        fail(
            "SOURCE_CONFLICT_UNRESOLVED",
            "Resolve material source conflicts and preserve clean source snapshots "
            "before publication.",
        )
    return {
        "sources": states,
        "open_conflicts": [c.id for c in unresolved],
        "non_governing_sources": superseded,
    }


def resolve(db, mode, at=None):
    at = at or instant(db)
    head = registry(db, mode)
    if not head:
        return [], {"family": suites.FAMILY, "environment": mode, "epoch": 0, "packs": []}, None
    published = [exists(db, Pack, ident) for ident in head.publication_manifest_json["published"]]
    active = [
        p
        for p in published
        if aware(p.effective_from) <= at
        and (p.effective_until is None or at < aware(p.effective_until))
        and p.id not in head.publication_manifest_json["suspended"]
    ]
    boundaries = [aware(p.effective_from) for p in published if aware(p.effective_from) > at] + [
        aware(p.effective_until) for p in active if p.effective_until
    ]
    # Overlapping versions require explicit resolution, never newest-page-wins.
    manifest = {
        "family": suites.FAMILY,
        "environment": mode,
        "epoch": head.registry_epoch,
        "packs": [
            {
                "id": p.id,
                "hash": p.content_hash,
                "version": p.version,
                "sources": sources_current(db, p),
            }
            for p in active
        ],
        "suspended": list(head.publication_manifest_json["suspended"]),
    }
    return active, manifest, min(boundaries) if boundaries else None


def pack_view(db, pack):
    head = registry(db, pack.environment)
    state = (
        "SUSPENDED"
        if head and pack.id in head.publication_manifest_json["suspended"]
        else "PUBLISHED"
        if head and pack.id in head.publication_manifest_json["published"]
        else "UNPUBLISHED_CANDIDATE"
    )
    return {
        **view(pack),
        "publication_state": state,
        "test_runs": [
            view(r)
            for r in db.scalars(
                select(TestRun)
                .where(TestRun.pack_revision_id == pack.id)
                .order_by(TestRun.created_at.desc(), TestRun.id.desc())
            )
        ],
        "publication_events": [
            view(r)
            for r in db.scalars(
                select(Publication)
                .where(Publication.pack_revision_id == pack.id)
                .order_by(Publication.created_at.desc(), Publication.id.desc())
            )
        ],
        "rules": [
            view(r) for r in db.scalars(select(Rule).where(Rule.pack_revision_id == pack.id))
        ],
    }


def supported_scope(db, ctx):
    require(db, ctx.user, ctx.org_id, "organization.read")
    return {
        "sources": [
            view(s)
            for s in db.scalars(select(Source).order_by(Source.created_at.desc(), Source.id))
        ],
        "source_conflicts": [
            view(c)
            for c in db.scalars(
                select(SourceConflict).order_by(SourceConflict.created_at.desc(), SourceConflict.id)
            )
        ],
        "items": [
            pack_view(db, p)
            for p in db.scalars(select(Pack).order_by(Pack.created_at.desc(), Pack.id))
        ],
        "limitations": [
            "Specified application requirements only; no government clearance, "
            "tax-rate determination or unsupported-scope waiver."
        ],
    }


def create_conflict(db, ctx, ident, payload):
    registry_lock(db, True)
    require(db, ctx.user, ctx.org_id, "regulation.source.register")
    for ident in payload.source_ids:
        exists(db, Source, ident)
    row = SourceConflict(
        source_ids=[str(i) for i in payload.source_ids],
        issue=payload.issue,
        scope_json=payload.scope,
        created_by_user_id=ctx.user.id,
    )
    db.add(row)
    record(db, ctx, "REGULATION_SOURCE_CONFLICT_RECORDED", row)
    for mode in ("SIMULATION", "PRODUCTION"):
        head = registry(db, mode)
        if head:
            head.registry_epoch += 1
            head.updated_at = instant(db)
    return view(row)


def resolve_conflict(db, ctx, ident, payload):
    registry_lock(db, True)
    require(db, ctx.user, ctx.org_id, "regulation.pack.review")
    row = exists(db, SourceConflict, ident)
    if row.status != "OPEN":
        fail("CONCURRENT_CHANGE", "This source conflict is already resolved.", status=409)
    independent(ctx, row.created_by_user_id)
    if not set(str(i) for i in payload.governing_source_ids) <= set(row.source_ids):
        fail(
            "VALIDATION_ERROR",
            "Governing interpretation must refer to the recorded sources.",
            status=422,
        )
    row.resolution_json = payload.model_dump(mode="json")
    row.status, row.resolved_by_user_id, row.resolved_at = "RESOLVED", ctx.user.id, instant(db)
    for mode in ("SIMULATION", "PRODUCTION"):
        head = registry(db, mode)
        if head:
            head.registry_epoch += 1
            head.updated_at = instant(db)
    record(db, ctx, "REGULATION_SOURCE_CONFLICT_RESOLVED", row)
    return view(row)
