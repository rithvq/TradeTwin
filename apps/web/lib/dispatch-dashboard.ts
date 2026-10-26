import type { DispatchAction } from "./guarded-dispatch";
import type { ComputationTraceData } from "./computation-trace";

export const DISPATCH_CHANGED = "tradetwin:operations-changed";
export const DISPATCH_STORAGE = "tt-operations-updated";
export type DispatchLink = { label: string; href: string };
export type DispatchRow = {
  consignment_id: string;
  reference: string;
  trade_id: string;
  trade_reference: string;
  execution_mode: string;
  movement_status: string;
  action: DispatchAction;
  state: string;
  readiness_state: string;
  current_stage: string;
  reason_codes: string[];
  expiring_soon: boolean;
  expires_at: string | null;
  checked_at: string;
  links: DispatchLink[];
};
export type DispatchDashboard = {
  organization_id: string;
  checked_at: string;
  total: number;
  next_cursor: string | null;
  expiring_within_seconds: number;
  counts: {
    ready_to_move: number;
    awaiting_evidence_or_review: number;
    expiring_soon: number;
    blocked: number;
  };
  items: DispatchRow[];
};
export type DispatchStage = {
  number: number;
  name: string;
  status: string;
  reason_codes: string[];
  facts: Record<string, string | number | boolean | null>;
  items: {
    label: string;
    status: string;
    reason_codes: string[];
    description?: string | null;
  }[];
};
export type DispatchJourney = {
  consignment_id: string;
  reference: string;
  trade_id: string;
  action: DispatchAction;
  execution_mode: string;
  checked_at: string;
  readiness_state: string;
  historical: boolean;
  stages: DispatchStage[];
  links: DispatchLink[];
  evidence_changes: {
    status: string;
    detail_status: string;
    reason_codes: string[];
    transitions: { document_type: string; basis: string; code: string }[];
    notice: string;
  };
  calculation: ComputationTraceData | null;
  binding: {
    notice: string;
    items: {
      label: string;
      status: string;
      reference: string | null;
      reason_codes: string[];
    }[];
    manifest_path: string | null;
  };
  validity: {
    detail_status: string;
    notice: string;
    start_inputs?: { code: string; at: string }[];
    expiry_inputs?: { code: string; at: string }[];
    start_limited_by?: string[];
    expiry_limited_by?: string[];
    evaluation_deadlines?: { code: string; at: string }[];
  };
  post_dispatch_alerts: { code: string; severity: string }[];
};

export function announceOperationalChange() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(DISPATCH_CHANGED));
  try {
    localStorage.setItem(DISPATCH_STORAGE, crypto.randomUUID());
  } catch {
    /* Same-tab refresh still works. */
  }
}

export function dispatchLabel(value: string) {
  return value.toLowerCase().replaceAll("_", " ").replaceAll(":", " · ");
}
