# Document Desk: Phase 3

Documents are a separate evidence layer over commercial Phase 1 and operational
Phase 2. They never rewrite accepted terms, allocations, movement, receipts,
inspection, payment obligations/acknowledgments, carrier consent or GST registration.
Production dispatch readiness remains `NOT_ASSESSED` for Phase 4.

## Setup

Keep your existing `.env`, OAuth configuration, database volumes and document key ring.
Run from the repository root:

```powershell
python scripts/init-document-key.py
docker compose up -d --build
docker compose ps
```

This creates a worker credential once alongside the existing encryption key ring;
neither is committed or printed. PostgreSQL migrations are additive and preserve
existing identifiers. The document worker uses the Shipment Service database and
Redis transactional outbox. Document Service owns encrypted MinIO bytes and derived
artifacts; the Shipment Service owns permissions, jobs and evidence records.
Open `http://localhost:3000/documents` after OAuth sign-in. Existing shipment document
pages and uploads remain available. The trade's Documents tab links to its register.

ClamAV is now included on the internal Compose network without a published port.
Allow time for its signature database to initialise. Missing/unavailable scanners
leave uploaded files quarantined; there is no production scan bypass. Retry an
upload after the scanner becomes healthy. ClamAV can need several GB of host RAM;
set `CLAMAV_IMAGE` to your maintained deployment image when appropriate.

## Implemented

- Immutable source versions reusing Phase 2 attachment IDs; PDF/JPEG/PNG and supported
  e-invoice JSON; hashes, file metadata, page previews and encrypted extraction artifacts.
- Real native PDF text extraction using pypdf/pdfplumber, PDFium safe rasterisation,
  labelled/table-row capture, lossless JSON numbers and local QR decoding without URL visits.
- Optional Tesseract OCR adapter. No OCR executable is installed by default:
  `OCR_UNAVAILABLE` plus `PARTIAL` and manual transcription is the honest fallback.
- Durable stage jobs, outbox/Redis delivery, leased attempts, heartbeat, three-attempt
  retry ceiling, backoff, cancellation, deduplication and historical reprocessing.
- Source-linked observations; separate immutable human snapshots and exact-hash review
  submissions; corrections preserve raw values, source, reason, actor and time.
- Explicit line mappings to accepted order lines/consignment items, decimal quantity
  caps, exact units and 40/60 allocation without duplicating the document total.
- Duplicate hints limited to readable documents; explicit alias/canonical selection
  retains all original files and prevents alias quantity/financial aggregation.
- `PH3_DOCUMENT_DATA_CHECKS_V1`: 28 data-reconciliation checks. Missing comparison
  input is `UNKNOWN`, unsupported profiles are `NOT_EVALUATED`, draft checks are
  `PROVISIONAL`. These are not statutory applicability or fraud conclusions.
- Snapshot-based freshness for commercial revisions, plans, assignments, receipt
  heads, payments, related documents, mappings and trust policies. Stale results remain
  in history; a late worker cannot silently label changed inputs current.
- Exact compact RS256 verification against server-controlled trusted keys, separately
  from issuer trust, revocation and authority status. PDF signature validation is
  explicitly `UNSUPPORTED` in this deployment.
- Organisation-bound read-only provider adapter, independent timestamped observations,
  manual portal attestations labelled `MANUAL_REPORTED`, and filtered evidence export.
- Contributions in the existing eight modules: Documents desk; Shipments exception links;
  Compliance dimensions; Graph provenance; Risk exception signals; Optimizer versioned
  context; Regulations check-pack/adapter limitations; Evidence immutable history.

## Permissions And Privacy

Assign explicit organisation membership capabilities through the existing onboarding:
`SELLER_DOCUMENT_OPERATOR`, `SELLER_DOCUMENT_REVIEWER`, `BUYER_DOCUMENT_REVIEWER`.
`ORG_ADMIN` and commercial approval alone do not grant review authority.
Finance capabilities are required for payment evidence; financial-document read
permission remains enforced even through jobs, Graph, Risk, manifests and previews.
Integration administrators use `INTEGRATION_ADMINISTRATOR` to configure providers,
not to approve documents or accepted commercial terms.

Registration defaults to owner-only visibility. `READ_REVIEWED` shares submitted
facts, not raw extraction, source previews or original download. Original download
is a separate grant. Shares never bypass type sensitivity or recipient membership.
Carriers/drivers cannot read invoice prices, signed invoice JSON, payment evidence,
internal review notes or raw provider responses. Approved operational projections
are limited to allowlisted fields and the active accepted assignment; revocation
takes effect on the next access check. Own LR/GR/POD historical evidence is retained.
Tokens for previews/downloads expire in 60 seconds and require a fresh permission
check. Raw provider responses stay encrypted and are absent from ordinary responses.
Structured evidence ledgers use PostgreSQL JSONB with application authorization;
production additionally needs encrypted database volumes/backups and least-privilege
database access. This phase does not claim application-level encryption of every
relational/JSONB evidence field.

## Configuration And Limits

See `.env.example`. Defaults: 20 MiB/file, 100 pages, 25 million source image pixels,
10 million render pixels/page, 1 million extracted characters, 300-second parse
deadline, and Unix child-process 512 MiB address-space limit. Parsing runs in a
disposable network-disabled child. Native Windows does not provide the same Unix
RLIMIT enforcement; use Linux containers for deployment. Missing values and absent
provider confidence stay null. Quantity strings are `NUMERIC(20,6)`; money is integer
INR paise, never a JavaScript float. ISO dates and timezone-aware UTC timestamps are
separate. Arithmetic tolerance defaults to one paise and is configurable.

To use real OCR, install Tesseract in your custom Document Service image and set
`DOCUMENT_OCR_ENGINE=tesseract`. It remains local; no document LLM is used.
External OCR/model extraction, if added later, must be separately consented and
must obey the same strict canonical/provenance validators.

Authority integration is **not preconfigured** and does not scrape government portals.
Register a server secret binding through your secret manager, not browser JSON:

```json
{
  "organization_id": "YOUR_ORGANISATION_UUID",
  "provider_environment": "LIVE",
  "base_url": "https://YOUR_AUTHORISED_PROVIDER",
  "access_token": "SERVER_SECRET",
  "read_only_paths": {"GSTIN_AUTHORITY_LOOKUP": "/registration-status"}
}
```

Store it as `DOCUMENT_PROVIDER_BINDING_YOUR_BINDING`, allowlist the host with
`DOCUMENT_VERIFICATION_ALLOWED_HOSTS`, then configure a connection referencing only
`YOUR_BINDING`. Bindings must match the organisation and environment; production
cannot use sandbox/simulation responses as live evidence. The generic adapter expects
normalised documented fields; provider-specific credentials/payload contracts still
need the provider's authorised integration. There are no IRN/EWB generation, filing,
bank verification, tax-rate approval or dispatch APIs in this phase.

## Development Demo

Set `DOCUMENT_DEMO_ENABLED=true` only in development, rebuild Shipment/Document
Services, and wait for ClamAV. Bind existing OAuth identity subjects to the Phase 2
demo roles through a private JSON identity map, for example:

```json
{"seller-operations": "YOUR_EXISTING_PROFILE_SUBJECT", "buyer-receiver": "OTHER_PROFILE_SUBJECT"}
```

Use different authenticated accounts to demonstrate separation. The seed creates
neither demo passwords nor sign-in bypasses. `seller-operations` receives document
review authority; `buyer-receiver` receives buyer document review authority.

```powershell
docker compose exec shipment-service python -m app.document_desk.cli --identity-map /path/to/private-identity-map.json
```

The identity map must be mounted/readable inside the container; do not commit it.
For an isolated command-line fixture setup without assigning real OAuth profiles,
omit `--identity-map`. The default namespace is `phase3`; `--reset` creates a fresh
namespace rather than deleting audit evidence. Fixture party names describe the
default namespace; names in a reset namespace can correctly show reconciliation
differences. Files are actually encrypted, hashed and malware-scanned, never marked
clean by a client declaration. The nine actual fixture originals and their hashes
are in `data/fixtures/document-desk/manifest.json`. Only a public simulation key is
stored; no production/private signing key is bundled.

Walkthrough:

1. Open the accepted 100-NOS agreement and the 40/60 consignments.
2. Open `invoice.pdf`, run native-text extraction, inspect its hash and highlighted fields.
3. Confirm values, save the review draft, then submit its exact snapshot.
4. Open the scanned invoice and explicitly select `SIMULATION_FIXTURE`; correct the
   single controlled GSTIN transcription error with a reason and submit the review.
5. Preserve/compare both presentations; designate the scanned copy as an alias before
   mapping the canonical invoice 40/60. Its gross 1,180,000 paise appears once.
   The goods payment basis stays 1,000,000 paise; printed synthetic tax does not alter it.
6. Review packing/transport documents, select the consignment comparison scope and run checks.
7. Extract `signed-payload.json` and request the simulation-only signed-payload check.
8. Extract `mismatched-invoice.pdf`, check its signed QR, then run data checks: valid
   signature and altered printed number are independent, simultaneously visible results.
9. Request an unconfigured live lookup: show `NOT_CONFIGURED`, never invented verification.
10. Make an explicit supported Phase 2 planning/assignment change, view `STALE`, and
    run a new assessment while retaining the previous snapshot.
11. Open Graph/Evidence/Optimizer to trace provenance, export the permission-filtered
    manifest, and inspect `document_context_hash` with its evidence references.

SIMULATION fixtures are not OCR performance benchmarks or government responses.
No future production-dispatch functionality is enabled by completing this demo.

## Tests And Contracts

```powershell
python -m pytest apps/api services/shipment-service services/compliance-service services/document-service services/intelligence-service
python scripts/document-browser-check.py
python scripts/export-document-contracts.py
```

The browser walkthrough starts and cleans up disposable authenticated services and
test sessions; it uses real encrypted bytes, native parsing, rendering and signature
verification. Only ClamAV's INSTREAM transport response is stubbed in that isolated
test; it does not test malware-detection quality. Desktop/mobile screenshots go to
`artifacts/audit/document-desk`. It requires an existing frontend production build.
PostgreSQL concurrency tests run when `TRADE_TEST_DATABASE_URL` points to a disposable
database; every test uses a random temporary schema. CI runs both regressions and
the authenticated browser walkthrough. Public contracts are generated in `docs/postman`.
Existing health-check scripts and normal Docker deployment procedure still apply.

Independent status dimensions must never be collapsed into a universal "Verified"
badge. This phase provides decision-support evidence, not legal, tax, banking or
government authorisation.
