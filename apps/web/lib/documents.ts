export const documentApiBaseUrl =
  process.env.NEXT_PUBLIC_DOCUMENT_SERVICE_URL ?? "http://localhost:8013";

export type DocumentType =
  | "commercial_invoice"
  | "packing_list"
  | "certificate_of_origin"
  | "safety_certificate"
  | "transit_declaration";

export type TradeDocument = {
  id: string;
  shipment_id: string;
  consignment_id: string | null;
  shipment_event_id: string | null;
  document_type: DocumentType;
  filename: string;
  content_type: string;
  size_bytes: number;
  jurisdiction: string | null;
  verification_status: "UPLOADED" | "EXTRACTED" | "NEEDS_REVIEW" | "FAILED";
  extracted_fields: Record<string, unknown>;
  extracted_text_preview: string;
  document_number: string | null;
  document_date: string | null;
  uploaded_at: string;
  extracted_at: string | null;
};

export type EvidenceRecord = {
  id: string;
  assessment_id: string;
  shipment_id: string;
  consignment_id: string | null;
  rule_id: string;
  rule_title: string;
  regulation_version: string;
  regulation_source_url: string;
  document_id: string | null;
  shipment_event_id: string | null;
  jurisdiction: string;
  procedure_type: string;
  evidence_type: "DOCUMENT_SUPPORTS_RULE" | "DOCUMENT_MISSING" | "EVENT_TRIGGERED_RULE";
  explanation: string;
  created_at: string;
  document: TradeDocument | null;
};

export const documentTypeOptions: Array<{ value: DocumentType; label: string }> = [
  { value: "commercial_invoice", label: "Commercial invoice" },
  { value: "packing_list", label: "Packing list" },
  { value: "certificate_of_origin", label: "Certificate of origin" },
  { value: "safety_certificate", label: "Safety certificate" },
  { value: "transit_declaration", label: "Transit declaration" },
];

export async function documentFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const headers = new Headers(options?.headers);
  const isFormData =
    typeof FormData !== "undefined" && options?.body instanceof FormData;

  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${documentApiBaseUrl}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function verificationBadgeClasses(status: string): string {
  const base = "rounded px-2.5 py-1 text-xs font-medium";
  if (status === "EXTRACTED") {
    return `${base} bg-emerald-100 text-emerald-900`;
  }
  if (status === "NEEDS_REVIEW") {
    return `${base} bg-amber-100 text-amber-900`;
  }
  if (status === "FAILED") {
    return `${base} bg-red-100 text-red-900`;
  }
  return `${base} bg-slate-100 text-slate-700`;
}
