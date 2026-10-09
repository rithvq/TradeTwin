export const complianceApiBaseUrl =
  process.env.NEXT_PUBLIC_COMPLIANCE_SERVICE_URL ?? "/api/services/compliance";
const demoAuthToken = process.env.NEXT_PUBLIC_DEMO_AUTH_TOKEN;

export type ComplianceStatus =
  | "COMPLIANT"
  | "CONDITIONALLY_COMPLIANT"
  | "NON_COMPLIANT"
  | "INSUFFICIENT_INFORMATION";

export type UploadedDocumentMetadata = {
  document_id: string;
  document_type: string;
  filename?: string;
  consignment_id?: string | null;
  shipment_event_id?: string | null;
  jurisdiction?: string | null;
  metadata?: Record<string, unknown>;
};

export type ApplicableRuleResult = {
  rule_id: string;
  title: string;
  jurisdiction: string;
  procedure_type: string;
  version: string;
  effective_from: string;
  effective_to: string | null;
  source_url: string;
  required_documents: string[];
  status: ComplianceStatus;
  missing_documents: string[];
  supporting_document_ids: string[];
  shipment_event_id: string | null;
  violation: string | null;
  recommended_action: string | null;
};

export type ComplianceRule = {
  rule_id: string;
  title: string;
  jurisdiction: string;
  procedure_type: string;
  effective_from: string;
  effective_to: string | null;
  source_url: string;
  version: string;
  conditions: Record<string, unknown>;
  required_documents: string[];
  outcome_if_failed: {
    status: ComplianceStatus;
    violation: string;
    recommended_action: string;
  };
};

export type ConsignmentComplianceResult = {
  consignment_id: string;
  product_name: string;
  jurisdiction: string;
  procedure_type: string;
  status: ComplianceStatus;
  applicable_rules: ApplicableRuleResult[];
  missing_documents: string[];
  violations: string[];
  recommended_action: string;
};

export type ComplianceAssessmentResult = {
  shipment_id: string;
  status: ComplianceStatus;
  applicable_rules: ApplicableRuleResult[];
  missing_documents: string[];
  violations: string[];
  recommended_action: string;
  consignment_results: ConsignmentComplianceResult[];
};

export type ComplianceAssessment = {
  id: string;
  shipment_id: string;
  job_id: string | null;
  status: ComplianceStatus;
  created_at: string;
  result: ComplianceAssessmentResult;
};

export type ConflictSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type ConsistencyConflict = {
  conflict_id: string;
  conflict_type: string;
  severity: ConflictSeverity;
  title: string;
  details: string;
  why_this_matters: string;
  consignment_id: string | null;
  consignment_name: string | null;
  document_ids: string[];
  event_ids: string[];
};

export type ConsistencyCheck = {
  shipment_id: string;
  checked_at: string;
  conflicts: ConsistencyConflict[];
};

export type InformationGainQuestion = {
  question_id: string;
  shipment_id: string;
  consignment_id: string | null;
  attribute_key: string;
  question: string;
  impact_score: number;
  affects_rules: string[];
  why_this_matters: string;
  answer_options: string[];
};

export type QuestionAnswerResult = {
  question: InformationGainQuestion;
  answer: string;
  assessment: ComplianceAssessment;
};

export type RouteOption = {
  route_id: string;
  label: string;
  description: string;
  countries: string[];
  per_consignment_paths: Record<string, string[]>;
  is_current_route: boolean;
  legal_status: "VALID" | "INVALID";
  compliance_status: ComplianceStatus;
  score: number;
  estimated_duty: number;
  fta_eligible: boolean;
  risk_score: number;
  estimated_delay_hours: number;
  required_documents: string[];
  missing_documents: string[];
  invalid_reasons: string[];
  corrective_actions: string[];
  is_recommended: boolean;
};

export type RouteOptimization = {
  shipment_id: string;
  generated_at: string;
  recommended_route_id: string | null;
  options: RouteOption[];
};

export type RegulationSummary = {
  id: string;
  rule_id: string;
  title: string;
  jurisdiction: string;
  procedure_type: string;
  version: string;
};

export type Regulation = {
  id: string;
  status: string;
  rule: ComplianceRule;
  created_at: string;
  published_at: string | null;
};

export type RegulationPublishResult = {
  regulation: Regulation;
  message: string;
};

export type ShipmentImpact = {
  shipment_id: string;
  shipment_reference: string;
  previous_status: ComplianceStatus;
  new_status: ComplianceStatus;
  triggering_regulation: RegulationSummary;
  corrective_action: string;
  affected_consignment_ids: string[];
  route_recommendation: RouteOption | null;
  assessment: ComplianceAssessment;
};

export type ImpactAnalysis = {
  generated_at: string;
  analyzed_regulations: RegulationSummary[];
  impacted_shipments: ShipmentImpact[];
};

export async function complianceFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const headers = complianceHeaders(options?.headers);
  const response = await fetch(`${complianceApiBaseUrl}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function complianceFetchBlob(
  path: string,
  options?: RequestInit,
): Promise<Blob> {
  const headers = complianceHeaders(options?.headers);
  const response = await fetch(`${complianceApiBaseUrl}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  return response.blob();
}

export function complianceHeaders(existingHeaders?: HeadersInit): Headers {
  const headers = new Headers(existingHeaders);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = typeof window === "undefined" ? demoAuthToken :
    window.sessionStorage.getItem("tradetwin-token") ?? demoAuthToken;
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

export function buildDemoDocumentPackage(
  shipmentId: string,
  includeBatteryCertificate: boolean,
  domestic = false,
): UploadedDocumentMetadata[] {
  if (domestic) return (includeBatteryCertificate ? ["tax_invoice", "eway_bill", "packing_list"] : ["tax_invoice"]).map(document_type => ({ document_id: `demo-${shipmentId}-${document_type}`, document_type, filename: `${document_type}.txt`, jurisdiction: "India", metadata: { source: "demo-ui" } }));
  const baseDocuments = [
    "commercial_invoice",
    "packing_list",
    "export_declaration",
    "import_declaration",
    "certificate_of_origin",
    "transit_declaration",
  ];
  const documentTypes = includeBatteryCertificate
    ? [...baseDocuments, "lithium_battery_safety_certificate"]
    : baseDocuments;

  return documentTypes.map((documentType) => ({
    document_id: `demo-${shipmentId}-${documentType}`,
    document_type: documentType,
    filename: `${documentType}.pdf`,
    metadata: { source: "demo-ui" },
  }));
}
