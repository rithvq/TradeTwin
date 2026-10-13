import type { Values } from "./trades";

export type DispatchAction = "PICKUP_CONFIRMED" | "DEPARTED";
export type BoundDocument = {
  id: string;
  label: string;
  document_type: string;
  reference: Values;
  assets: { attachment_id: string; content_type: string }[];
  verification_results: {
    id: string;
    check_type: string;
    method: string;
    environment: string;
    fresh_until: string;
    signed_qr_artifact_id?: string;
  }[];
  manual_attestations: {
    id: string;
    check_type: string;
    reported_by_user_id: string;
    review_outcome: string;
  }[];
};
export type ComplianceContext = {
  holds?: {
    id: string;
    active: boolean;
    reason: string;
    reason_code: string;
    events: { id: string; event_type: string; created_by_user_id: string }[];
  }[];
  trade_id: string;
  consignment_id: string;
  context_version: number;
  etag: string;
  inherited_facts: Values;
  recipient_baseline: Values;
  recipient_confirmation: Values | null;
  effective_facts: Values;
  heads: Record<string, string | number | null>;
  capabilities: string[];
  available_scope_codes: string[];
  available_commodity_codes: string[];
  documents: BoundDocument[];
  private_turnover_sources: BoundDocument[];
  loading_manifest: Values | null;
  historical_movement_notice: string | null;
  fact_revisions: {
    id: string;
    content_hash: string;
    submitted_for_review: boolean;
    prepared_by_user_id: string;
    effective: boolean;
    facts?: Values;
  }[];
  transport_evidence: {
    id: string;
    evidence_type: string;
    evidence: Values;
    prepared_by_user_id: string;
    review_outcome: string;
    can_review: boolean;
  }[];
};
export type Requirement = {
  id: string;
  rule_id: string;
  requirement_code: string;
  rule_class: string;
  applicability: string;
  outcome: string;
  mandatory: boolean;
  severity: string;
  explanation: string;
  source_ids: string[];
  remedies_json: string[];
  observed_json: {
    comparison?: Values;
    correction_links?: { url: string; document_version_id: string }[];
  };
};
export type Evaluation = {
  id: string;
  action: DispatchAction;
  execution_mode: string;
  job_state: string;
  decision: string;
  freshness: string;
  context_version: number;
  evaluation_hash: string;
  release_review_blockers: string[];
  warning_acknowledgment_options: {
    id: string;
    requirement_id: string;
    reason: string;
  }[];
  packet_source_options: {
    document_type: string;
    document_version_id: string;
    assets: { attachment_id: string }[];
    signed_qr_artifact_ids: string[];
  }[];
  evaluated_at: string;
  valid_until: string;
  requirements: Requirement[];
  blockers: string[];
  warnings: string[];
  coverage: Values;
  limitations: string[];
  release_reviews: {
    id: string;
    decision: string;
    reviewer_user_id: string;
    valid_until: string;
  }[];
  packets: {
    id: string;
    packet_hash: string;
    assignment_id: string;
    carry_methods: string[];
    acknowledgments: { id: string; driver_user_id: string }[];
  }[];
};
export type Authorization = {
  id: string;
  authorisation_id: string;
  action: DispatchAction;
  execution_mode: string;
  loading_manifest_revision_id: string;
  effective_state: string;
  expires_at: string;
  valid_from: string;
};
export type Readiness = {
  state: string;
  reasons: string[];
  context_version: number;
  execution_mode: string;
  evaluation: Evaluation | null;
  authorisation: Authorization | null;
  historical_notice: string | null;
  operational_alerts?: {
    code: string;
    severity: string;
    explanation: string;
  }[];
};
export type Packet = {
  id: string;
  packet_hash: string;
  assignment_id: string;
  execution_mode: string;
  effective_state: string;
  valid_until: string;
  items: {
    id: string;
    representation_type: string;
    carry_method: string;
    source_reference_json?: Values;
  }[];
};

export const transportTypes = [
  "VEHICLE_RC",
  "VEHICLE_INSURANCE",
  "FITNESS_CERTIFICATE",
  "PUC_CERTIFICATE",
  "GOODS_PERMIT",
  "PERMIT_AUTHORISATION",
  "DRIVER_LICENCE",
  "CARGO_INSURANCE",
];

export function beforeExpiry(value?: string): boolean {
  return !!value && Date.now() < Date.parse(value);
}
