import type { Values } from "./trades";

export type JourneyTask = {
  task_key: string;
  basis_hash: string;
  title: string;
  explanation: string;
  module_code: string;
  priority: "BLOCKER" | "ACTION_REQUIRED" | "INFORMATIONAL";
  status: string;
  actionable_by_current_user: boolean;
  internal_screen_target: string;
  user_seen_at: string | null;
  user_state_etag: string | null;
};
export type Journey = {
  trade_id: string;
  trade_reference: string;
  execution_mode: string;
  computed_at: string;
  source_context_version: number;
  projection_freshness: string;
  commercial: { agreement_status: string };
  fulfilment: {
    ordered_lines: (Record<string, string> & {
      trade_line_ref: string;
      description: string;
      uqc: string;
    })[];
  };
  consignments: {
    consignment_id: string;
    consignment_reference: string;
    movement_status: string;
    assignment_status: string;
    historical_authorisation_coverage: string;
    reported_motion: string;
    application_protection_state: string | null;
    pickup_readiness: { state: string };
    departure_readiness: { state: string };
  }[];
  goods_finance?: Values;
  freight?: Values[];
  tasks: JourneyTask[];
  limitations: string[];
};
export type ReplayResult = {
  id: string;
  job_state: string;
  input_integrity?: string;
  recomputation?: string;
  original_business_as_of?: string;
  engine_version?: string;
  current_readiness?: string;
  differences?: {
    path: string;
    original_value: unknown;
    recomputed_value: unknown;
    reason: string;
  }[];
  limitations?: string[];
};
export type ReadinessContext = {
  deployment_id?: string;
  manifest_hash?: string;
  manifest: Values | null;
  qualification_outcome: string;
  activation_state?: string;
  controls?: Values;
  etag?: string;
  limitations: string[];
};
export type ReadinessRun = {
  id: string;
  job_state: string;
  result_hash: string | null;
  qualification_outcome: string | null;
  checks: {
    id: string;
    definition_id: string;
    check_code: string;
    outcome: string;
    provenance: string;
    observation: { reason: string };
    limitations: string[];
  }[];
};
export type DemoWorkspace = {
  id: string;
  trade_id: string | null;
  etag: string;
  state: string;
  scenario_manifest_hash: string;
  virtual_as_of: string;
  limitations: string[];
  scenario: { steps: { step_code: string }[] };
};
export type DemoRun = {
  id: string;
  workspace_id: string;
  workspace_etag: string;
  trade_id: string | null;
  status: string;
  etag: string;
  current_step_code: string | null;
  receipts: {
    id: string;
    step_code: string;
    receipt: { status: string; actor_user_id: string };
  }[];
};
