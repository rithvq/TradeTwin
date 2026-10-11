import type { IndianLocation } from "./shipments";
import { complianceApiBaseUrl } from "./compliance";

export type Place = IndianLocation & { longitude?: number; latitude?: number };

export type Option = {
  offer_id: string;
  carrier: string;
  reference: string;
  quoted_price_inr: number;
  duration_hours: number;
  generalized_cost_inr: number;
  blocking_reasons: string[];
  source_url: string;
  source_reference: string;
  valid_until: string;
  explanation: string;
  historical_hours: number | null;
  eligible: boolean;
  compliance: {
    status: string;
    missing_documents: string[];
    applicable_rules: {
      rule_id: string;
      version: string;
      source_url: string;
      title: string;
    }[];
  };
};

export type RecordRow = {
  id: string;
  kind: string;
  recorded_at: string;
  carrier?: string;
  reference?: string;
  source_url?: string;
  total_price_inr?: number;
  valid_until?: string;
  options?: Option[];
  recommended_offer_id?: string | null;
  inputs_changed?: boolean;
  previous_decision_id?: string;
  input_fingerprint?: string;
  unknown_factors?: string[];
  scope?: string;
};

export type Memory = {
  records: RecordRow[];
  corridors: Record<string, { sample_count: number; median_hours: number }>;
  routing_configured: boolean;
  catalog_mode: string;
};

export async function stateRelationRequest<T>(
  shipmentId: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(
    `${complianceApiBaseUrl}/state-relations/${shipmentId}${path}`,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok) {
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Check required fields, route stops and administrator permissions.",
    );
  }
  return data as T;
}
