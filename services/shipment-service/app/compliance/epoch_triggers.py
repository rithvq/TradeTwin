"""Migration helpers for atomic scope moves and changes outside the HTTP/audit adapters."""


def uuid_text(value, postgres):
    if postgres:
        return f"CAST({value} AS TEXT)"
    return " || '-' || ".join(
        f"substr({value}, {start}, {size})"
        for start, size in ((1, 8), (9, 4), (13, 4), (17, 4), (21, 12))
    )


def install(connection):
    postgres = connection.dialect.name == "postgresql"
    generation = "gen_random_uuid()" if postgres else "lower(hex(randomblob(16)))"
    for table, queries, columns, code in definitions(postgres):
        changed = " OR ".join(
            f"OLD.{c} IS DISTINCT FROM NEW.{c}" if postgres else f"OLD.{c} IS NOT NEW.{c}"
            for c in columns
        )
        if postgres:
            pieces = []
            for ref, condition in (("OLD", "TG_OP <> 'INSERT'"), ("NEW", "TG_OP <> 'DELETE'")):
                selection = " UNION ".join(q.format(ref=ref) for q in queries)
                pieces.append(
                    f"IF {condition} THEN FOR scope IN {selection} ORDER BY 1 LOOP "
                    + upsert("scope", code, generation)
                    + "; END LOOP; END IF;"
                )
            guard = (
                f"IF TG_OP = 'UPDATE' AND NOT ({changed}) THEN RETURN NEW; END IF;"
                if columns
                else ""
            )
            connection.exec_driver_sql(
                f"CREATE FUNCTION calc_epoch_{table}() RETURNS trigger AS $$ "
                f"DECLARE scope TEXT; BEGIN {guard} {' '.join(pieces)} "
                "RETURN NULL; END; $$ LANGUAGE plpgsql"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER calculation_scope_epoch AFTER INSERT OR UPDATE OR DELETE "
                f"ON {table} FOR EACH ROW EXECUTE FUNCTION calc_epoch_{table}()"
            )
        else:
            for action, refs in (
                ("INSERT", ("NEW",)),
                ("UPDATE", ("OLD", "NEW")),
                ("DELETE", ("OLD",)),
            ):
                condition = f"WHEN {changed}" if action == "UPDATE" and columns else ""
                statements = []
                for ref in refs:
                    for query in queries:
                        statements.append(
                            upsert("scope_key", code, generation, query.format(ref=ref))
                        )
                connection.exec_driver_sql(
                    f"CREATE TRIGGER calc_epoch_{table}_{action.lower()} AFTER {action} "
                    f"ON {table} {condition} BEGIN {'; '.join(statements)}; END"
                )


def upsert(scope, code, generation, query=None):
    fields = "(scope_key, generation_id, epoch, last_change_code, changed_at)"
    values = f"VALUES ({scope}, {generation}, 1, '{code}', CURRENT_TIMESTAMP)"
    if query:
        values = (
            f"SELECT scope_key, {generation}, 1, '{code}', CURRENT_TIMESTAMP "
            f"FROM ({query}) WHERE scope_key IS NOT NULL"
        )
    return (
        f"INSERT INTO compliance_dependency_scope_epochs {fields} {values} ON CONFLICT (scope_key) "
        "DO UPDATE SET epoch = compliance_dependency_scope_epochs.epoch + 1, "
        f"last_change_code = '{code}', changed_at = CURRENT_TIMESTAMP"
    )


def definitions(postgres):
    def trade(column, group):
        return f"'trade:' || {uuid_text(column, postgres)} || ':{group}'"

    def direct(column, group):
        return f"SELECT {trade(column, group)} AS scope_key"

    def cn(group):
        return (
            f"SELECT {trade('c.trade_id', group)} AS scope_key FROM op_consignments c "
            "WHERE c.id = {ref}.consignment_id"
        )

    yield (
        "doc_documents",
        [
            f"SELECT 'trade:' || {uuid_text('{ref}.trade_id', postgres)} "
            "|| ':DOC:' || {ref}.document_type AS scope_key"
        ],
        [
            "trade_id",
            "document_type",
            "current_version_id",
            "effective_fact_revision_id",
            "current_mapping_revision_id",
            "canonical_document_id",
            "lifecycle_status",
        ],
        "DOCUMENT_ELIGIBILITY_CHANGED",
    )
    yield (
        "op_operational_attachments",
        [
            f"SELECT 'trade:' || {uuid_text('d.trade_id', postgres)} || ':DOC:' "
            "|| d.document_type AS scope_key FROM doc_version_assets a "
            "JOIN doc_document_versions v ON v.id = a.document_version_id "
            "JOIN doc_documents d ON d.id = v.document_id WHERE a.attachment_id = {ref}.id"
        ],
        ["sha256", "security_state"],
        "SOURCE_SECURITY_CHANGED",
    )
    yield (
        "op_transport_assignments",
        [cn("ASSIGNMENT")],
        [
            "consignment_id",
            "vehicle_id",
            "driver_user_id",
            "status",
            "vehicle_snapshot",
            "driver_snapshot",
            "booking_start_at",
            "booking_end_at",
        ],
        "ASSIGNMENT_CHANGED",
    )
    yield (
        "op_vehicles",
        ["SELECT 'global:VEHICLES' AS scope_key"],
        ["active", "registration_number", "vehicle_json"],
        "VEHICLE_CHANGED",
    )
    yield (
        "consignment_compliance_heads",
        [cn(group) for group in ("FACTS", "BINDING", "LOADING")],
        [
            "current_fact_revision_id",
            "current_binding_revision_id",
            "current_loading_manifest_revision_id",
        ],
        "EVIDENCE_BINDING_OR_FACTS_CHANGED",
    )
    yield (
        "trades",
        [direct("{ref}.id", "TERMS")],
        ["accepted_revision_id"],
        "ACCEPTED_TERMS_CHANGED",
    )
    yield (
        "op_consignments",
        [direct("{ref}.trade_id", "LOADING")],
        [
            "trade_id",
            "plan_json",
            "source_accepted_revision_id",
            "active_assignment_id",
            "revision_alignment",
        ],
        "QUANTITY_OR_PLAN_CHANGED",
    )
    yield (
        "transport_evidence_revisions",
        [direct("{ref}.trade_id", "TRANSPORT")],
        [],
        "TRANSPORT_EVIDENCE_CHANGED",
    )
    yield (
        "transport_evidence_reviews",
        [
            f"SELECT {trade('e.trade_id', 'TRANSPORT')} AS scope_key "
            "FROM transport_evidence_revisions e WHERE e.id = {ref}.evidence_revision_id"
        ],
        [],
        "TRANSPORT_EVIDENCE_REVIEWED",
    )
    yield (
        "doc_verification_results",
        [
            f"SELECT {trade('d.trade_id', 'VERIFICATION')} AS scope_key "
            "FROM doc_verification_checks k "
            "JOIN doc_document_versions v ON v.id = k.document_version_id "
            "JOIN doc_documents d ON d.id = v.document_id WHERE k.id = {ref}.verification_check_id"
        ],
        [],
        "VERIFICATION_STATE_CHANGED",
    )
    yield (
        "doc_verification_connections",
        ["SELECT 'global:VERIFICATION' AS scope_key"],
        ["status", "adapter_version", "allowed_check_types_json", "provider_environment"],
        "VERIFICATION_CONNECTION_CHANGED",
    )
    yield (
        "doc_trusted_verification_keys",
        ["SELECT 'global:VERIFICATION' AS scope_key"],
        [
            "status",
            "effective_from",
            "effective_until",
            "key_fingerprint",
            "registry_policy_version",
        ],
        "TRUSTED_KEY_CHANGED",
    )
