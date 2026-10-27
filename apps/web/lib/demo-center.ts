export type IntegratedDemo = {
  id: string;
  status: "QUEUED" | "RUNNING" | "READY" | "FAILED";
  expires_at: string;
  expired: boolean;
  execution_mode: "SIMULATION";
  trade_id: string | null;
  organization_id: string | null;
  consignment_id: string | null;
  next_step_index: number;
  steps: { code: string; label: string; actor: string }[];
  receipts: {
    id: string;
    step_code: string;
    status: string;
    error_code: string | null;
    result: { summary?: string } | null;
  }[];
  route_study_ids: string[];
  sample_document_version_id: string | null;
  limitations: string[];
};

export const DEMO_CHANGED = "tradetwin:demo-changed";
const ACTIVE = "tt-demo-active";
type DemoSelection = {
  id: string;
  org: string;
  previousOrg: string | null;
  previousRole: string | null;
};
export function activeDemo(): DemoSelection | null {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(ACTIVE) ?? "null",
    ) as DemoSelection | null;
    return value &&
      typeof value.id === "string" &&
      typeof value.org === "string"
      ? value
      : null;
  } catch {
    return null;
  }
}
export function enterDemo(id: string, org: string) {
  const previous = activeDemo();
  sessionStorage.setItem(
    ACTIVE,
    JSON.stringify({
      id,
      org,
      previousOrg: previous
        ? previous.previousOrg
        : localStorage.getItem("tt-commercial-org"),
      previousRole: previous
        ? previous.previousRole
        : localStorage.getItem("tt-commercial-role"),
    }),
  );
  localStorage.setItem("tt-commercial-org", org);
  localStorage.setItem("tt-commercial-role", "SELLER");
  window.dispatchEvent(new Event(DEMO_CHANGED));
}
export function exitDemo() {
  const current = activeDemo();
  if (current) {
    if (current.previousOrg)
      localStorage.setItem("tt-commercial-org", current.previousOrg);
    else localStorage.removeItem("tt-commercial-org");
    if (current.previousRole)
      localStorage.setItem("tt-commercial-role", current.previousRole);
    else localStorage.removeItem("tt-commercial-role");
  }
  sessionStorage.removeItem(ACTIVE);
  window.dispatchEvent(new Event(DEMO_CHANGED));
}
