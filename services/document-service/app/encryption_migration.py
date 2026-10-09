"""Idempotent, pre-serving migration of legacy document data into encrypted storage."""

import json

from sqlalchemy import inspect, text

from app.encryption import JSON_MARKER, MAGIC, field_context, keyring, seal, unseal

FIELDS = {
    "documents": [
        "filename",
        "extracted_fields",
        "extracted_text_preview",
        "document_number",
        "document_date",
    ],
    "evidence_records": ["explanation"],
}


def migrate_encryption(engine, storage):
    keyring()  # Fail closed before making schema or data changes.
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(884923)"))
            columns = {c["name"]: c for c in inspect(connection).get_columns("documents")}
            for name in ("filename", "document_number", "document_date"):
                if str(columns[name]["type"]).upper() != "TEXT":
                    connection.execute(
                        text(
                            f'ALTER TABLE documents ALTER COLUMN "{name}" TYPE TEXT '
                            f'USING "{name}"::text'
                        )
                    )
        # Raw connections intentionally cover all owners, before any HTTP traffic is accepted.
        for table, fields in FIELDS.items():
            rows = connection.execute(text(f"SELECT * FROM {table}"))
            for row in rows.mappings():
                owner = row["owner_id"]
                changes = {}
                for field in fields:
                    value = row[field]
                    if value is None:
                        continue
                    context = field_context(f"{table}.{field}", owner)
                    if field == "extracted_fields":
                        value = json.loads(value) if isinstance(value, str) else value
                        if isinstance(value, dict) and JSON_MARKER in value:
                            unseal(value[JSON_MARKER].encode(), context)
                            continue
                        encrypted = {
                            JSON_MARKER: seal(json.dumps(value).encode(), context).decode()
                        }
                        changes[field] = json.dumps(encrypted)
                    else:
                        value = str(value)
                        if value.encode().startswith(MAGIC):
                            unseal(value.encode(), context)
                            continue
                        changes[field] = seal(value.encode(), context).decode()
                if table == "documents":
                    old_key = row["object_key"]
                    storage.encrypt_existing(old_key)
                    new_key = f"profiles/{owner}/shipments/{row['shipment_id']}/{row['id']}.enc"
                    if old_key != new_key:
                        plaintext = unseal(
                            storage.stored_bytes(old_key), f"document-object|{old_key}"
                        )
                        storage.put_bytes(new_key, seal(plaintext, f"document-object|{new_key}"))
                        changes["object_key"] = new_key
                if changes:
                    assignments = []
                    for field in changes:
                        parameter = f":{field}"
                        if field == "extracted_fields" and engine.dialect.name == "postgresql":
                            parameter = f"CAST({parameter} AS jsonb)"
                        assignments.append(f'"{field}" = {parameter}')
                    connection.execute(
                        text(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = :id"),
                        {**changes, "id": row["id"]},
                    )
