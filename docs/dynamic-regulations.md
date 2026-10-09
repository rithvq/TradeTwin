# Source-backed regulation updates

TradeTwin supports on-demand official-source retrieval and optional OpenAI-compatible
drafting at `/dashboard/regulations`. This is a reviewed document-requirement catalog,
not an autonomous legal adviser or a complete live feed of Indian law.

## Operation

1. An administrator fetches an official HTML page or a text-based PDF (up to 2 MB,
   50 pages) from the allowlisted GST Council, CBIC-GST or e-way bill documentation hosts.
   Use the final HTTPS URL: redirects are deliberately rejected. A notification index
   is discovery material; fetch the relevant notification PDF before proposing its rule.
2. PostgreSQL stores the source text, retrieval time, SHA-256 and change indicator,
   scoped to the signed-in profile. Retrieval failures leave existing rules unchanged.
3. Optionally request an AI draft, or submit `{ "rule": <ComplianceRule>, "quote": "..." }`
   using the schema in the compliance service OpenAPI docs. A supporting quotation
   must occur in the saved source and its URL must match. Schema checks reject unsupported
   conditions. These checks establish traceability, not correctness of legal interpretation.
4. Review effective dates, applicability, exceptions, amendments, required documents and
   outcome against the primary notification. Add a rationale, approve, then publish.
   Source-backed drafts cannot publish without approval and an unchanged source fetched
   in the last seven days. Published versions remain immutable through this workflow.
5. Run existing regulation impact analysis to reassess active shipments. Historical
   assessments retain their rule versions and evidence. Publication does not automatically
   rewrite historical assessments.

## Configuration

Set `REGULATION_CATALOG_MODE=reviewed` in `.env` to exclude all bundled rules from
runtime assessments and impact analysis. Only database-published versions are used.
An empty catalog produces insufficient information, not an automatic pass.
The default `demo` preserves existing demonstrations and is visibly labelled in the UI.
Existing manually published company/demo policies remain published in either mode;
use a clean profile/catalog for a legal-only evaluation deployment.

For optional drafting, configure `REGULATION_LLM_BASE_URL`, `REGULATION_LLM_MODEL`, and
`REGULATION_LLM_API_KEY`. Keep the provider endpoint HTTPS and operator-controlled.
No key is needed for manual source-backed drafts. Only public source text is sent to
the provider, never shipment data or uploaded private PDFs. There is no mock legal answer.

Rebuild with `docker compose up -d --build compliance-service web`.
The new profile-owned snapshot and review tables are additive and created at startup.

## Boundaries and guardrails

The evaluator stays deterministic. Dynamic versions can change thresholds, jurisdictions,
dates, required documents and outcomes without code changes, within the existing supported
ordinary domestic road-supply scope. New procedural semantics still require tested engine
capabilities; arbitrary code, expressions and model-generated executable logic are rejected.
Retrieved pages are untrusted data. Fetches use a host allowlist, public-address check,
TLS, no redirects, a timeout and size limits. Use outbound network controls in production
as additional protection against DNS rebinding. A scanned PDF needs manual handling.

There is no background polling, comprehensive notification discovery, automatic amendment
consolidation or automatic legal publication. Previously published rules are not revoked
on a website change or outage; they remain the last reviewed catalog, not a guarantee of
current law. Review snapshot freshness before relying on assessments. Approval currently
requires an administrator but not a separate second administrator. Production rollout
needs legal ownership, independent review, monitored refresh jobs and coverage validation.

Sources: https://gstcouncil.gov.in/cgst-tax-notification and
https://docs.ewaybillgst.gov.in/html/faq_new.html (guidance, not a substitute for notifications).
