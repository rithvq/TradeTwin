import type { Values } from "@/lib/trades";

export type CorridorImpact = {
  outcome: string;
  items: Array<{
    event_revision_id?: string;
    headline?: string;
    edge_key?: string;
    outcome: string;
    spatial_match?: string;
    temporal_match?: string;
    source_reference?: string;
    maximum_delay_seconds?: number | null;
    limitations: string[];
  }>;
  nominal_arrival_at?: string;
  worst_case_arrival_at?: string | null;
  maximum_additional_delay_seconds: number | null;
  limitations: string[];
};
export type RecoveryCase = {
  id: string;
  etag: string;
  status: string;
  protection_state: string;
  motion: string;
  stationary_epoch: number;
  driver_response_allowed: boolean;
  case_json: Values;
};
export type DynamicContext = {
  consignment_id: string;
  reference: string;
  execution_mode: string;
  movement_status: string;
  etag: string;
  dynamic_context_hash: string;
  current_route_plan_revision_id: string | null;
  coverage: Values;
  impact: CorridorImpact | null;
  events: Values[];
  recovery_cases: RecoveryCase[];
  capabilities: string[];
};
export type CorridorRegistry = {
  source_connections: Array<{
    id: string;
    provider_code: string;
    status: string;
    environment: string;
    etag: string;
    connection_json: Values;
  }>;
  policies: Array<{
    id: string;
    policy_code: string;
    content_hash: string;
    created_by_user_id: string;
    active: boolean;
    policy_json: Values;
    actions: Values[];
  }>;
  mappings: Values[];
  incidents: Array<{
    id: string;
    etag: string;
    environment: string;
    visibility: string;
    revisions: Array<{
      id: string;
      content_hash: string;
      created_by_user_id: string;
      state: string;
      event_json: Values;
      actions: Values[];
    }>;
  }>;
};
