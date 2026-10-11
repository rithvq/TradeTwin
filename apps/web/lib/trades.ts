export type Values = Record<string, unknown>;
export type FieldError = { path: string; code: string; message: string };
export type Membership = {
  organization_id: string;
  legal_name: string | null;
  profile_status: string;
  capabilities: string[];
  permissions: {
    permission_code: string;
    trade_id: string | null;
    capability: string;
  }[];
  registrations: {
    id: string;
    gstin: string;
    state_code: string;
    verification_status: string;
  }[];
};
export type Me = {
  user: { id: string; display_name: string; email: string };
  memberships: Membership[];
};
export type ReferenceData = {
  states: Record<string, string>;
  unit_codes: string[];
  capability_permissions: Record<string, string[]>;
};
export type Revision = {
  id: string;
  revision_number: number;
  revision_kind: string;
  terms_hash: string;
  facts: Values;
  pricing_summary: Values;
  created_at: string;
};
export type Trade = {
  trade_id: string;
  reference: string;
  agreement_status: string;
  etag: string;
  current_revision_id: string | null;
  revision_number: number;
  accepted_revision: Revision | null;
  current_candidate_revision: Revision | null;
  active_offer: {
    id: string;
    revision_id: string;
    terms_hash: string;
    status: string;
    expires_at: string;
    purpose: string;
  } | null;
  pending_amendment: {
    id: string;
    status: string;
    reason: string;
    proposer_organization_id: string;
  } | null;
  approval_progress: {
    party_role: string;
    decision: string;
    decided_at: string | null;
  }[];
  pricing_summary: Values;
  next_actions: string[];
  next_action_owners?: {
    participant_role: string;
    capability: string;
    action: string;
  }[];
  counterparty?: {
    organization_id: string;
    legal_name: string;
    trade_name: string | null;
  } | null;
  validation_errors: FieldError[];
  dispatch_readiness: "NOT_ASSESSED";
};
export type Partner = {
  organization_id: string;
  legal_name: string;
  trade_name: string | null;
  registration_position: string;
  registrations: Membership["registrations"];
  trading_locations: { id: string; label: string; address: Values }[];
};
export type Organization = Values & {
  organization_id: string;
  etag: string;
  profile_status: string;
  missing_fields: FieldError[];
  registrations: Membership["registrations"];
  locations: {
    id: string;
    label: string;
    address: Values;
    visibility: string;
  }[];
};
export type EvidenceEvent = {
  id: string;
  actor_name: string;
  actor_organization_id: string;
  action: string;
  occurred_at: string;
  revision_id: string | null;
  subject_id: string;
  subject_type: string;
  terms_hash: string | null;
  summary: Values;
};

export class TradeApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public fields: FieldError[] = [],
    public status = 0,
  ) {
    super(message);
  }
}

export async function tradeRequest<T>(
  path: string,
  org?: string,
  method = "GET",
  body?: unknown,
  etag?: string,
  key?: string,
): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (org) headers.set("X-Organization-Id", org);
  if (method !== "GET")
    headers.set("Idempotency-Key", key ?? crypto.randomUUID());
  if (etag) headers.set("If-Match", etag);
  const response = await fetch(`/api/services/shipment/api/v1${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const result = await response.json();
  if (!response.ok)
    throw new TradeApiError(
      result.error?.code ?? "REQUEST_FAILED",
      result.error?.message ?? result.detail ?? "Trade Service unavailable",
      result.error?.field_errors ?? [],
      response.status,
    );
  return result as T;
}

export function getValue(values: Values, path: string): unknown {
  return path
    .split(".")
    .reduce<unknown>(
      (value, key) =>
        value && typeof value === "object" ? (value as Values)[key] : undefined,
      values,
    );
}
export function setValue(values: Values, path: string, value: unknown): Values {
  const result = structuredClone(values);
  const keys = path.split(".");
  let target = result;
  for (const key of keys.slice(0, -1)) {
    if (!target[key] || typeof target[key] !== "object") target[key] = {};
    target = target[key] as Values;
  }
  target[keys[keys.length - 1]] = value;
  return result;
}
export function editableFacts(facts: Values): Values {
  const result = structuredClone(facts);
  delete result.initiated_by_role;
  for (const key of ["bill_from", "bill_to"]) {
    const party = result[key] as Values | undefined;
    if (party)
      result[key] = Object.fromEntries(
        Object.entries(party).filter(([name]) =>
          ["organization_id", "registration_id", "billing_address"].includes(
            name,
          ),
        ),
      );
  }
  result.items = ((result.items ?? []) as Values[]).map((item) =>
    Object.fromEntries(
      Object.entries(item).filter(
        ([key]) =>
          ![
            "line_no",
            "line_before_discount_minor",
            "line_quoted_total_minor",
            "line_tax_estimate_minor",
          ].includes(key),
      ),
    ),
  );
  return result;
}
export function displayTime(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  }).format(new Date(value));
}
export function displayMoney(value: unknown): string {
  if (typeof value !== "string" || !/^\d+$/.test(value)) return "Not assessed";
  const amount = BigInt(value);
  return `INR ${(amount / BigInt(100)).toLocaleString("en-IN")}.${(amount % BigInt(100)).toString().padStart(2, "0")}`;
}
export function localTimeInput(value: unknown) {
  if (typeof value !== "string" || !value) return "";
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return "";
  return new Date(instant.getTime() + 330 * 60000).toISOString().slice(0, 16);
}
