import type { Values } from "./trades";

export type FreightQuote = {
  id: string;
  content_hash?: string;
  quote_hash?: string;
  head_etag?: string;
  vehicle_id: string;
  profile_revision_id: string;
  route_template_revision_id: string;
  lifecycle: string;
  effective_expiration: string;
  quote_json: Values;
};
export type FreightRFQ = {
  selection_requests?: { id: string; lifecycle: string }[];
  id: string;
  request_hash: string;
  lifecycle: string;
  freshness?: string;
  etag: string;
  execution_mode: string;
  response_deadline: string;
  request: {
    pickup_location_revision_id: string;
    drop_location_revision_id: string;
    requested_pickup_window_start: string;
    requested_pickup_window_end: string;
    required_arrival_by: string | null;
    service_requirement_codes: string[];
    operational_projection: {
      cargo: Values;
      pickup: Values;
      drop: Values;
      route_templates: {
        id: string;
        hash: string;
        state_sequence: string[];
        ordered_node_keys: string[];
      }[];
    };
  };
  quotes: FreightQuote[];
};
export type FreightSelection = {
  id: string;
  proposal_hash: string;
  quote_hash: string;
  lifecycle: string;
  etag: string;
  proposed_assignment_id: string | null;
  commitment_id: string | null;
  proposal: {
    quote_revision_id: string;
    carrier_organisation_id: string;
    acknowledged_limitations_required: string[];
    selected_route_snapshot: Values;
    selected_timing_snapshot: Values;
    comparison_cost_snapshot?: Values;
  };
  decisions: { role: string; decision: string }[];
};
export type FreightContext = {
  consignment_id: string;
  reference: string;
  execution_mode: string;
  freight_payer_organisation_id: string;
  freight_payer_basis: Values;
  coordinating_organisation_id: string;
  current_assignment_id: string | null;
  expected_consignment_row_version: number;
  compliance_context_version: number;
  consignment_etag: string;
  context_etag: string;
  capabilities: string[];
  price_visible: boolean;
  pickup_address_hash: string;
  drop_address_hash: string;
  pickup_location_revision_id: string | null;
  drop_location_revision_id: string | null;
  inherited: { origin_state_code: string; destination_state_code: string };
  datasets: { id: string; dataset_code: string; version: string }[];
  locations: { id: string; address_role: string; location_json: Values }[];
  rfqs: FreightRFQ[];
  runs: {
    id: string;
    job_state: string;
    freshness: string;
    evaluated_as_of: string;
  }[];
  selection: FreightSelection | null;
  route_plan: { route_plan_json: Values } | null;
};
export type FreightCost = {
  carrier_payable_minor: string | null;
  external_cost_minor: string;
  recipient_tax_cash_estimate_minor: string;
  scenario_contingent_charge_minor: string;
  comparison_total_minor: string | null;
  known_partial_subtotal_minor: string;
  cost_completeness: string;
  price_basis: string;
  unknown_cost_categories: string[];
  calculation_steps: Values[];
};
export type FreightScenario = {
  scenario_code: string;
  planning_outcome: string;
  ranking_eligibility?: string;
  estimated_departure_at: string;
  estimated_arrival_at: string;
  estimated_completion_at: string;
  route: {
    distance_meters: number;
    estimated_driving_seconds: number;
    state_sequence: string[] | null;
    data_provenance: Values;
  };
  cost?: FreightCost;
  why_excluded: string[];
  planning_constraint_results: {
    requirement_code: string;
    outcome: string;
    explanation: string;
  }[];
  candidate_compliance_results: Values[];
  post_selection_actions: string[];
  informational_limitations: string[];
};
export type FreightCandidate = {
  offer_label?: string;
  candidate_id: string;
  candidate_hash: string;
  quote_revision_id: string;
  quote_hash: string;
  carrier_organisation_id: string;
  vehicle_id: string;
  scenarios: Record<string, FreightScenario>;
};
export type FreightRun = {
  eligible_baseline_comparison?: {
    lowest_cost_offer: string;
    baseline_offer: string;
    additional_cost_for_earlier_arrival_minor: string;
    basis: string;
  };
  id: string;
  input_hash: string;
  engine_version?: string;
  result_hash: string | null;
  job_state: string;
  freshness: string;
  price_visible: boolean;
  execution_mode: string;
  evaluated_as_of: string;
  objective?: string;
  candidates: FreightCandidate[];
  rankings?: Record<
    string,
    Record<
      string,
      {
        candidate_id: string;
        rank: number;
        pareto_member: boolean;
        explanation: string;
      }[]
    >
  >;
};

export function freightMoney(value: string | null | undefined) {
  if (value == null) return "Incomplete";
  const minor = BigInt(value);
  const rupees = minor / BigInt(100);
  return `INR ${rupees.toLocaleString("en-IN")}.${(minor % BigInt(100)).toString().padStart(2, "0")}`;
}
