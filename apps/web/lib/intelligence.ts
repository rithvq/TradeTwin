import type { Consignment } from "./shipments";

export const intelligenceApiBaseUrl =
  process.env.NEXT_PUBLIC_INTELLIGENCE_SERVICE_URL ?? "http://localhost:8014";

export type HSCodeRecommendation = {
  hs_code: string;
  title: string;
  confidence: number;
  human_review_required: boolean;
  tariff_notes: string;
  matched_terms: string[];
};

export type HSClassificationResponse = {
  provider: string;
  model: string;
  confidence_threshold: number;
  recommendations: HSCodeRecommendation[];
};

export type RiskFactor = {
  factor: string;
  impact: string;
  explanation: string;
};

export type RiskAssessment = {
  id: string;
  shipment_id: string;
  model_version: string;
  inspection_probability: number;
  rejection_probability: number;
  expected_clearance_delay_hours: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  warning: string;
  features: Record<string, unknown>;
  risk_factors: RiskFactor[];
  created_at: string;
};

export async function intelligenceFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${intelligenceApiBaseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function getLatestRiskAssessment(
  shipmentId: string,
): Promise<RiskAssessment | null> {
  const response = await fetch(
    `${intelligenceApiBaseUrl}/shipments/${shipmentId}/risk-assessment`,
  );

  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<RiskAssessment>;
}

export function consignmentToClassificationBody(consignment: Consignment) {
  return {
    consignment_id: consignment.id,
    product_name: consignment.product_name,
    product_description: consignment.product_description,
    country_of_origin: consignment.country_of_origin,
    destination_country: consignment.destination_country,
  };
}
