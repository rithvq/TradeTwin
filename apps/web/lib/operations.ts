import { type Values } from "./trades";

export type OperationalRecord = {
  dispatch_readiness?: string;
  id: string;
  execution_mode: "PRODUCTION" | "SIMULATION";
  created_at: string;
  etag?: string;
  request_id?: string;
};
export type QuantitySummary = {
  consignment_item_id: string;
  line_ref: string;
  description: string;
  uqc: string;
  allocated_quantity: string;
  loaded_quantity: string | null;
  received_quantity: string;
  accepted_quantity: string;
  rejected_quantity: string;
  pending_inspection_quantity: string;
  awaiting_receipt_quantity: string;
  short_quantity: string;
};
export type Inspection = OperationalRecord & {
  entry_type: string;
  accepted_quantity: string;
  rejected_quantity: string;
  reverses_decision_id: string | null;
};
export type ReceiptLine = OperationalRecord & {
  consignment_item_id: string;
  delivered_quantity: string;
  uqc: string;
  observed_condition: string;
  accepted_quantity: string;
  rejected_quantity: string;
  pending_inspection_quantity: string;
  decisions: Inspection[];
};
export type Receipt = OperationalRecord & {
  head_etag: string;
  effective: boolean;
  received_at: string;
  supersedes_receipt_id: string | null;
  lines: ReceiptLine[];
};
export type Assignment = OperationalRecord & {
  consignment_id: string;
  carrier_organization_id: string;
  vehicle_id: string | null;
  driver_user_id: string | null;
  status: string;
  booking_start_at: string;
  booking_end_at: string;
  suitability_json: Values | null;
  vehicle_snapshot: Values | null;
  driver_snapshot: Values | null;
  consignment?: Consignment;
};
export type Consignment = OperationalRecord & {
  trade_id: string;
  reference: string;
  etag: string;
  row_version: number;
  source_accepted_revision_id: string;
  coordinating_organization_id: string;
  planning_status: string;
  movement_status: string;
  revision_alignment: string;
  plan_json: Values;
  pickup_address_snapshot: Values;
  delivery_address_snapshot: Values;
  active_assignment_id: string | null;
  current_delivery_closure_id: string | null;
  items: (OperationalRecord & {
    line_ref: string;
    allocated_quantity: string;
    uqc: string;
    description_snapshot: string;
    specification_snapshot: string;
    cargo_declarations_snapshot: Values;
  })[];
  assignments: Assignment[];
  documents?: Attachment[];
  events: (OperationalRecord & {
    event_type: string;
    occurred_at: string;
    notes: string | null;
    payload_json: Values;
    projection_applied: boolean;
  })[];
  receipts?: Receipt[];
  receipt_summary?: QuantitySummary[];
  closures?: (OperationalRecord & { quantity_summary_json: Values })[];
  allowed_actions: string[];
};
export type Dispute = OperationalRecord & {
  trade_id: string;
  consignment_id: string | null;
  dispute_json: Values;
  status: string;
  active_proposal_id: string | null;
  opened_by_organization_id: string;
  events: (OperationalRecord & {
    event_type: string;
    actor_organization_id: string;
    outcome: string | null;
    text: string;
    proposal_id: string | null;
  })[];
  allowed_actions: string[];
};
export type ScheduleLine = OperationalRecord & {
  obligation_ref: string;
  label: string;
  face_amount_minor: string;
  trigger: string;
  offset_days: number;
  fixed_due_on: string | null;
  trigger_met?: boolean;
  due_on?: string | null;
  net_allocated_minor?: string;
  remaining_minor?: string;
  overapplied_minor?: string;
  status?: string;
};
export type Schedule = OperationalRecord & {
  status: string;
  accepted_revision_id: string;
  content_hash: string;
  lines: ScheduleLine[];
  approvals: (OperationalRecord & {
    organization_id: string;
    decision: string;
  })[];
};
export type Payment = OperationalRecord & {
  amount_minor: string;
  paid_on: string;
  method: string;
  declared_reference: string | null;
  status: string;
  net_allocated_minor: string;
  pending_void_request:
    (OperationalRecord & { actor_organization_id: string }) | null;
  allocations: (OperationalRecord & {
    entry_type: string;
    amount_minor: string;
    obligation_ref: string;
    reverses_allocation_id: string | null;
  })[];
  decisions: (OperationalRecord & {
    decision: string;
    reason: string | null;
  })[];
};
export type Settlement = {
  execution_mode: string;
  pricing_basis: string;
  accepted_quoted_goods_total_minor: string;
  active_schedule_id: string | null;
  schedule_status: string;
  schedule_review_required: boolean;
  scheduled_goods_minor: string;
  reported_payment_minor: string;
  acknowledged_payment_minor: string;
  net_allocated_minor: string;
  unallocated_acknowledged_minor: string;
  outstanding_scheduled_minor: string;
  overapplied_minor: string;
  disputed_payment_minor: string;
  obligations: ScheduleLine[];
  payments: Payment[];
  schedules: Schedule[];
  allowed_actions: string[];
};
export type Attachment = OperationalRecord & {
  trade_id: string;
  consignment_id: string | null;
  original_name: string;
  content_type: string;
  size_bytes: number;
  sha256: string | null;
  security_state: string;
  verification_status: string;
  purpose: string;
  upload?: { url: string; method: string };
};
export type Operations = {
  trade_id: string;
  execution_mode: "PRODUCTION" | "SIMULATION";
  accepted_revision_id: string | null;
  agreement_status: string;
  row_version: number;
  etag: string;
  availability: {
    line_ref: string;
    description: string;
    uqc: string;
    ordered_quantity: string;
    reserved_quantity: string;
    available_quantity: string;
  }[];
  consignments: Consignment[];
  disputes: Dispute[];
  settlement: Settlement | null;
  documents: Attachment[];
  exceptions: {
    type: string;
    source_id: string;
    consignment_id?: string;
    fact_status: string;
    verification_status?: string;
  }[];
  graph: {
    nodes: { id: string; type: string; label: string }[];
    edges: { source: string; target: string; type: string }[];
  };
  allowed_actions: string[];
};
export type Candidate = {
  accepted_revision_id: string;
  status: string;
  questions: string[];
  lines: Values[];
  quoted_goods_total_minor: string;
  pricing_basis: string;
};

export const TRIGGERS = [
  "ORDER_CONFIRMATION",
  "FULL_DISPATCH",
  "FULL_DELIVERY",
  "FULL_ACCEPTANCE",
  "FIXED_DATE",
];
export const title = (value: string) =>
  value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());

export function netReversible(payment: Payment, allocationId: string): string {
  const original = payment.allocations.find((a) => a.id === allocationId);
  if (!original || original.entry_type !== "ALLOCATION") return "0";
  return (
    BigInt(original.amount_minor) -
    payment.allocations
      .filter((a) => a.reverses_allocation_id === allocationId)
      .reduce((sum, a) => sum + BigInt(a.amount_minor), BigInt(0))
  ).toString();
}
