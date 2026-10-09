# Confidential document storage

## Protection implemented

The document service encrypts PDF/TXT bytes before writing them to MinIO or the local
object store, using AES-256-GCM with a fresh 96-bit random nonce for every encryption.
Authentication binds ciphertext to the object key. New object keys contain opaque IDs,
not uploaded filenames. Decryption occurs inside the authorized document service for
local pypdf/pdfplumber extraction; there is no document-parsing LLM request.

The document database encrypts filenames, extracted field JSON, text previews, document
numbers, document dates and evidence explanations. Database ciphertext is authenticated
against its profile and column. Existing profile authorization still controls every read.
IDs, ownership, document type, size, status, jurisdiction and timestamps remain queryable
metadata. This is not blanket encryption of shipment, graph, Redis or assessment data.
Business details copied into those systems still require encrypted disks/backups and
appropriate access controls. Authorized API responses necessarily contain decrypted data.

Multipart bodies are bounded and kept in memory before encryption rather than spilling
to plaintext temporary files. Concurrent uploads still require deployment-level rate and
memory limits. Integrity failures do not fall back to plaintext. Missing/invalid keys
prevent startup. Raw parser exception messages are not saved as extracted fields.

Private product descriptions are not sent to the classification provider unless the
operator explicitly sets `ALLOW_PRIVATE_DATA_LLM=true`. Its default is false, with local
classification retained. Regulation drafting sends retrieved public government text only.
Encryption at rest does not protect data deliberately submitted to an external provider.

## Setup and deployment

From the repository root:

```powershell
python scripts/init-document-key.py
docker compose up -d --build document-service intelligence-service
```

The initializer creates `.secrets/document-keyring.json` once and never overwrites it.
It is excluded from Git and Docker build contexts. Docker mounts it read-only into the
document service, not other containers. On this Windows workstation the generated file
has also been restricted to the current user and SYSTEM. On another Windows machine,
restrict its ACL after generation; POSIX creation uses mode 0600. Production deployments
should supply the key ring from a managed secret store/KMS rather than a developer disk.

For running the document service outside Docker, set `DOCUMENT_ENCRYPTION_KEY_FILE` to
the absolute key-ring path. `DOCUMENT_ENCRYPTION_KEY` accepts a base64-encoded 32-byte key
as an alternative (primarily isolated tests), but a separately mounted secret is preferred.
Never put keys in client-side `NEXT_PUBLIC_*` variables or commit them. The key ring uses
`{"active":"key-id","keys":{"key-id":"base64-encoded-32-byte-key"}}`.

## Existing files and rollout

Back up the database, bucket and encryption key securely before the first deployment.
Stop document writes during the rollout and do not run old and new document-service
versions concurrently. Startup takes a PostgreSQL advisory lock, widens relevant legacy
columns to TEXT, encrypts existing database values and tracked document objects, and
verifies existing ciphertext. It does not accept requests until migration succeeds.
Migration is idempotent, but for large stores its initial scan may exceed health-check
startup deadlines; plan a maintenance window. Missing/corrupt tracked objects block startup
and require restoration from a backup, not generating a new key.

Legacy objects are encrypted in place before copying to opaque canonical keys. An
encrypted copy can remain under the old key for recovery, so old key names may still
reveal filenames. Untracked/orphan objects, old MinIO versions, historical backups,
database WAL, filesystem snapshots and freed disk blocks are not securely erased by this
migration. Apply storage encryption and retention policies to these separately. Do not
roll back to the old binary against the migrated database.

## Key recovery and rotation

Losing the key means losing access to encrypted documents. Back up the ring separately
from database/bucket backups and test recovery. To rotate, securely add a fresh random
32-byte key under a new ID, change `active`, retain all old keys and restart the service.
New writes use the new key; existing ciphertext remains readable with retained keys.
There is no automatic re-encryption job for removing old keys yet. Never replace the ring
with a newly generated one to resolve a startup failure.

## Remaining deployment requirements

This is server-side encryption at rest, not end-to-end encryption: the service must read
plaintext in memory to parse it. It does not protect against a compromised application
process or an administrator who can access both keys and data. Use HTTPS at the public
edge, TLS for remote service/database connections, private network policies, encrypted
volumes and backups, MFA, least-privilege storage credentials, access auditing, retention
controls and resource quotas before handling production confidential documents. Local
Docker endpoints remain development HTTP endpoints bound to localhost.

Verification includes ciphertext inspection, extraction round trips, nonce variation,
tamper/wrong-context rejection, missing-key behavior, retained-key rotation, profile
isolation, legacy migration idempotence and a MinIO client-contract test.
