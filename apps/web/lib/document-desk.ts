import { type Values } from "./trades";

export const documentTypes = [
  "TAX_INVOICE",
  "BILL_OF_SUPPLY",
  "DELIVERY_CHALLAN",
  "PACKING_LIST",
  "PURCHASE_ORDER",
  "LR_GR",
  "EWAY_BILL_COPY",
  "SIGNED_EINVOICE_JSON",
  "POD",
  "PAYMENT_EVIDENCE",
  "VEHICLE_RC",
  "VEHICLE_INSURANCE",
  "FITNESS_CERTIFICATE",
  "PUC_CERTIFICATE",
  "GOODS_PERMIT",
  "PERMIT_AUTHORISATION",
  "DRIVER_LICENCE",
  "CARGO_INSURANCE",
  "OTHER",
] as const;
export type DocumentRecord = {
  id: string;
  trade_id: string;
  label: string;
  document_type: string;
  owner_organization_id: string;
  current_version_id: string;
  effective_fact_revision_id: string | null;
  latest_draft_fact_revision_id: string | null;
  latest_job_id?: string | null;
  current_mapping_revision_id: string | null;
  declared_document_number: string | null;
  execution_mode: string;
  lifecycle_status: string;
  etag: string;
  canonical_document_id: string | null;
  status_dimensions: Record<string, string | null>;
  allowed_actions: string[];
  current_version: SourceVersion;
  versions: SourceVersion[];
  linked_subjects: Values[];
  assessments: Assessment[];
  verification_checks: VerificationCheck[];
  mapping_summary?: {
    document_line_ref: string;
    mapped_quantity: string;
    unmapped_quantity: string | null;
    uqc: string | null;
  }[];
  captured_identity?: {
    document_number: string | null;
    issue_date: string | null;
    issuer_name: string | null;
  };
};
export type SourceVersion = {
  id: string;
  document_id: string;
  version_number: number;
  source_manifest_hash: string;
  reason: string;
  assets: Values[];
  document?: DocumentRecord;
  selected_fact_revision_id?: string | null;
  is_current_source?: boolean;
};
export type ExtractionRun = {
  id: string;
  engine_kind: string;
  engine_name: string;
  created_at: string;
  proposed_document_json: Values;
};
export type Locator = {
  source_attachment_id: string;
  page_number?: number | null;
  text_start?: number | null;
  text_end?: number | null;
  json_pointer?: string | null;
  bounding_box?: { x0: number; x1: number; y0: number; y1: number } | null;
  coordinate_space?: string | null;
  text_artifact_id?: string | null;
};
export type Observation = {
  id: string;
  field_path: string;
  row_key: string | null;
  raw_text: string | null;
  normalised_value_json: unknown;
  extraction_method: string;
  provider_confidence: string | number | null;
  validation_status: string;
  source_locator_json: Locator;
  normalisation_warnings_json: string[];
};
export type FieldDecision = {
  field_path: string;
  observation_id: string | null;
  decision: string;
  effective_value_json: unknown;
  provenance: string;
  reason: string | null;
  source_locator_json: Locator | null;
};
export type FactRevision = {
  id: string;
  document_id: string;
  document_version_id: string;
  extraction_run_id: string | null;
  revision_number: number;
  canonical_document_json: Values;
  content_hash: string;
  etag: string;
  field_decisions: FieldDecision[];
};
export type Finding = {
  id: string;
  check_code: string;
  check_version: string;
  outcome: string;
  severity: string;
  message: string;
  expected_value_json: unknown;
  observed_value_json: unknown;
  expected_source_json: Values;
  observed_source_json: Values;
  limitations_json: string[];
};
export type Assessment = {
  id: string;
  document_version_id: string;
  fact_revision_id: string;
  mapping_revision_id: string | null;
  freshness: string;
  consistency: string;
  assessment_stage: string;
  findings: Finding[];
  created_at: string;
  check_pack_version: string;
};
export type VerificationCheck = {
  id: string;
  check_type: string;
  job_id: string;
  results: { id: string; freshness: string; result_json: Values }[];
};
export type Job = {
  id: string;
  status: string;
  stage: string;
  etag: string;
  last_error_code: string | null;
  attempts: Values[];
  extraction_run_ids: string[];
};
export type DocumentSummary = {
  documents: DocumentRecord[];
  signals: (Finding & {
    document_id: string;
    assessment_id: string;
    assessed_at: string;
    freshness: string;
  })[];
  graph: {
    nodes: { id: string; type: string; label: string; href: string }[];
    edges: { id: string; source: string; target: string; label: string }[];
  };
  dispatch_readiness: string;
  notice: string;
};

export function flattenDocument(
  value: Values,
  prefix = "",
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (["schema_version", "document_line_ref"].includes(key)) continue;
    const path = prefix ? `${prefix}.${key}` : key;
    if (key === "lines" && Array.isArray(item))
      for (const line of item as Values[])
        Object.assign(
          result,
          flattenDocument(line, `lines.${String(line.document_line_ref)}`),
        );
    else if (item && typeof item === "object" && !Array.isArray(item))
      Object.assign(result, flattenDocument(item as Values, path));
    else if (item !== null && item !== undefined) result[path] = item;
  }
  return result;
}
export function setDocumentField(
  value: Values,
  path: string,
  next: unknown,
): Values {
  const copy = structuredClone(value);
  const parts = path.split(".");
  let target = copy;
  if (parts[0] === "lines") {
    target = (copy.lines as Values[]).find(
      (line) => line.document_line_ref === parts[1],
    )!;
    target[parts[2]] = next;
  } else {
    for (const key of parts.slice(0, -1)) {
      if (!target[key]) target[key] = {};
      target = target[key] as Values;
    }
    target[parts.at(-1)!] = next;
  }
  return copy;
}
export function label(value: string) {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^./, (c) => c.toUpperCase());
}
export function printable(value: unknown) {
  if (value === null || value === undefined) return "Missing";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
