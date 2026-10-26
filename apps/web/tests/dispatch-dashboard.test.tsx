import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DispatchOverview } from "@/components/dashboard/dispatch-overview";
import {
  announceOperationalChange,
  type DispatchDashboard,
  type DispatchJourney,
  type DispatchStage,
} from "@/lib/dispatch-dashboard";
import { tradeRequest } from "@/lib/trades";

vi.mock("@/lib/trades", async (original) => ({
  ...(await original<typeof import("@/lib/trades")>()),
  tradeRequest: vi.fn(),
}));
const profile = {
  user: {
    id: "user",
    display_name: "User",
    email: "synthetic@example.invalid",
  },
  memberships: [
    { organization_id: "seller", legal_name: "Seller", permissions: [] },
    { organization_id: "other", legal_name: "Other company", permissions: [] },
  ],
};
const data: DispatchDashboard = {
  organization_id: "seller",
  checked_at: "2026-10-26T10:00:00Z",
  total: 1,
  next_cursor: null,
  expiring_within_seconds: 300,
  counts: {
    ready_to_move: 1,
    awaiting_evidence_or_review: 0,
    expiring_soon: 0,
    blocked: 0,
  },
  items: [
    {
      consignment_id: "cn",
      reference: "TT-CN-ONE",
      trade_id: "trade",
      trade_reference: "TT-TRADE",
      execution_mode: "SIMULATION",
      movement_status: "NOT_STARTED",
      action: "PICKUP_CONFIRMED",
      state: "READY",
      readiness_state: "READY",
      current_stage: "READY_TO_MOVE",
      reason_codes: [],
      expiring_soon: false,
      expires_at: null,
      checked_at: "2026-10-26T10:00:00Z",
      links: [
        {
          label: "Open compliance desk",
          href: "/shipments/trades/trade/operations?module=Compliance",
        },
      ],
    },
  ],
};
function journey(action: "PICKUP_CONFIRMED" | "DEPARTED"): DispatchJourney {
  return {
    consignment_id: "cn",
    reference: "TT-CN-ONE",
    trade_id: "trade",
    action,
    execution_mode: "SIMULATION",
    checked_at: data.checked_at,
    readiness_state: "READY",
    historical: false,
    links: data.items[0].links,
    evidence_changes: {
      status: "CURRENT",
      detail_status: "RECORDED",
      reason_codes: [],
      transitions: [],
      notice: "Search matches are not accepted evidence.",
    },
    calculation: {
      status: "RECORDED",
      strategy: "FULL",
      authoritative_strategy: "FULL",
      rules_total: 17,
      rules_recomputed: 17,
      rules_reused: 0,
      shadow_rules_reused: 0,
      shadow_equivalent: null,
      invalidation_reasons: [],
      rules: [],
      notice: "A new evaluation requires its own release workflow.",
    },
    binding: {
      notice: "A new evaluation requires a new release chain.",
      items: [
        {
          label: "Evaluation",
          status: "CURRENT",
          reference: "eval",
          reason_codes: [],
        },
        {
          label: "Driver acknowledgment",
          status: "MISSING",
          reference: null,
          reason_codes: [],
        },
      ],
      manifest_path: null,
    },
    validity: { detail_status: "NOT_RECORDED", notice: "Detail not recorded." },
    post_dispatch_alerts: [],
    stages: [
      "Evidence",
      "Snapshot",
      "Compliance",
      "Release",
      "Authorization",
      "Movement check",
      "Result",
    ].map<DispatchStage>((name, index) => ({
      number: index + 1,
      name,
      status: index >= 5 ? "PENDING" : index === 4 ? "ACTIVE" : "COMPLETE",
      facts:
        index === 2
          ? { strategy: "FULL", rules_recomputed: 17, rules_reused: 0 }
          : ({} as DispatchStage["facts"]),
      reason_codes: [],
      items: [],
    })),
  };
}
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(tradeRequest).mockImplementation(async (path) => {
    if (path === "/me") return profile;
    if (path.startsWith("/dispatch-dashboard")) return data;
    if (path.includes("dispatch-journey"))
      return journey(
        path.endsWith("DEPARTED") ? "DEPARTED" : "PICKUP_CONFIRMED",
      );
    throw new Error("Unexpected route");
  });
});
afterEach(() => vi.useRealTimers());

it("clears ready state if a refresh hangs and times out", async () => {
  vi.useFakeTimers();
  render(<DispatchOverview />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(screen.getByText("TT-CN-ONE")).toBeInTheDocument();
  vi.mocked(tradeRequest).mockImplementation(
    async (path, _org, _method, _body, _etag, _key, signal) => {
      if (path === "/me") return profile;
      return new Promise((_resolve, reject) =>
        signal?.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        ),
      );
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh dispatch" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20_000);
  });
  expect(screen.getByText("Current status unavailable")).toBeInTheDocument();
  expect(
    screen.queryByLabelText("Live dispatch counts"),
  ).not.toBeInTheDocument();
});

it("renders live counts and separate five-panel journeys without movement commands", async () => {
  render(<DispatchOverview />);
  await screen.findByText("TT-CN-ONE");
  expect(screen.getByLabelText("Live dispatch counts")).toHaveTextContent(
    "Ready to move1",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Pickup journey for TT-CN-ONE" }),
  );
  await screen.findByRole("heading", { name: "5. Validity" });
  for (const name of [
    "1. Evidence changes",
    "2. Rule calculation",
    "3. Exact binding",
    "4. Movement",
    "5. Validity",
  ])
    expect(screen.getByRole("heading", { name })).toBeInTheDocument();
  expect(screen.getByText(/Final check pending/)).toBeInTheDocument();
  expect(screen.getByText("0 reused")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", {
      name: /record pickup|record departed|approve release/i,
    }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Departure journey for TT-CN-ONE" }),
  );
  await screen.findByRole("heading", { name: /Departure journey/ });
  expect(tradeRequest).toHaveBeenCalledWith(
    "/consignments/cn/dispatch-journey?action=DEPARTED",
    "seller",
    "GET",
    undefined,
    undefined,
    undefined,
    expect.any(AbortSignal),
  );
});

it("removes old ready badges and counts when a refresh fails", async () => {
  render(<DispatchOverview />);
  await screen.findByText("TT-CN-ONE");
  vi.mocked(tradeRequest).mockImplementation(async (path) => {
    if (path === "/me") return profile;
    throw new Error("Service offline");
  });
  fireEvent.click(screen.getByRole("button", { name: "Refresh dispatch" }));
  await screen.findByText("Current status unavailable");
  expect(
    screen.queryByLabelText("Live dispatch counts"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("TT-CN-ONE")).not.toBeInTheDocument();
});

it("polls the list at 30 seconds and the open journey at 10 seconds and refreshes on changes", async () => {
  vi.useFakeTimers();
  render(<DispatchOverview />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Pickup journey for TT-CN-ONE" }),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  const count = (part: string) =>
    vi.mocked(tradeRequest).mock.calls.filter(([path]) => path.includes(part))
      .length;
  expect(count("dispatch-dashboard")).toBe(1);
  expect(count("dispatch-journey")).toBe(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(count("dispatch-dashboard")).toBe(1);
  expect(count("dispatch-journey")).toBe(2);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20_000);
  });
  expect(count("dispatch-dashboard")).toBe(2);
  expect(count("dispatch-journey")).toBe(4);
  await act(async () => {
    announceOperationalChange();
  });
  expect(count("dispatch-dashboard")).toBe(3);
  expect(count("dispatch-journey")).toBe(5);
});

it("clears previous organisation rows while a new organisation loads", async () => {
  render(<DispatchOverview />);
  await screen.findByText("TT-CN-ONE");
  vi.mocked(tradeRequest).mockImplementation(async () => new Promise(() => {}));
  fireEvent.change(
    screen.getByRole("combobox", { name: "Dispatch organisation" }),
    { target: { value: "other" } },
  );
  expect(screen.queryByText("TT-CN-ONE")).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("Live dispatch counts"),
  ).not.toBeInTheDocument();
});

it("shows actual incremental rule reuse only for an incremental evaluation", async () => {
  vi.mocked(tradeRequest).mockImplementation(async (path) => {
    if (path === "/me") return profile;
    if (path.startsWith("/dispatch-dashboard")) return data;
    const value = journey("PICKUP_CONFIRMED");
    value.calculation = {
      ...value.calculation!,
      strategy: "INCREMENTAL",
      authoritative_strategy: "INCREMENTAL",
      rules_recomputed: 3,
      rules_reused: 14,
    };
    return value;
  });
  render(<DispatchOverview />);
  await screen.findByText("TT-CN-ONE");
  fireEvent.click(
    screen.getByRole("button", { name: "Pickup journey for TT-CN-ONE" }),
  );
  await waitFor(() =>
    expect(screen.getByText("14 reused")).toBeInTheDocument(),
  );
});

it("explains shadow candidates, absence-to-presence and missing historical details without accepting evidence", async () => {
  vi.mocked(tradeRequest).mockImplementation(async (path) => {
    if (path === "/me") return profile;
    if (path.startsWith("/dispatch-dashboard")) return data;
    const value = journey("PICKUP_CONFIRMED");
    value.calculation = {
      ...value.calculation!,
      strategy: "SHADOW",
      authoritative_strategy: "FULL",
      shadow_rules_reused: 12,
      shadow_equivalent: true,
    };
    value.evidence_changes.transitions = [
      {
        document_type: "CARGO_INSURANCE",
        basis: "SINCE_EVALUATION",
        code: "EMPTY_SEARCH_GAINED_MATCH",
      },
    ];
    return value;
  });
  render(<DispatchOverview />);
  await screen.findByText("TT-CN-ONE");
  fireEvent.click(
    screen.getByRole("button", { name: "Pickup journey for TT-CN-ONE" }),
  );
  await screen.findByText(/12 calculations eligible for reuse/);
  expect(screen.getByText("0 reused")).toBeInTheDocument();
  expect(
    screen.getByText(/This does not establish accepted evidence/),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Detail not recorded.").length).toBeGreaterThan(0);
});

it("shows the server's recorded limiting deadline and an informational countdown", async () => {
  vi.useFakeTimers();
  vi.mocked(tradeRequest).mockImplementation(async (path) => {
    if (path === "/me") return profile;
    if (path.startsWith("/dispatch-dashboard")) return data;
    const value = journey("PICKUP_CONFIRMED");
    value.stages[4].status = "CONSUMED";
    value.stages[4].facts = {
      valid_from: data.checked_at,
      expires_at: "2026-10-26T10:00:05Z",
    };
    value.validity = {
      detail_status: "RECORDED",
      notice: "Expiry is exclusive.",
      expiry_limited_by: ["DRIVER_MOVEMENT_PERMISSION"],
      start_limited_by: ["ISSUED_AT"],
      expiry_inputs: [
        { code: "DRIVER_MOVEMENT_PERMISSION", at: "2026-10-26T10:00:05Z" },
      ],
    };
    return value;
  });
  render(<DispatchOverview />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Pickup journey for TT-CN-ONE" }),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(
    screen.getByText(/Window limited by:/).parentElement,
  ).toHaveTextContent("driver movement permission");
  expect(screen.getByTestId("dispatch-countdown")).toHaveTextContent("0m 5s");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(screen.getByTestId("dispatch-countdown")).toHaveTextContent(
    "Recorded window ended",
  );
  expect(screen.getByText("consumed")).toBeInTheDocument();
});

it("refreshes at the exclusive expiry boundary without a polling burst", async () => {
  vi.useFakeTimers();
  const started = Date.now();
  const serverTime = Date.parse(data.checked_at);
  vi.mocked(tradeRequest).mockImplementation(async (path) => {
    if (path === "/me") return profile;
    if (path.startsWith("/dispatch-dashboard")) return data;
    const value = journey("PICKUP_CONFIRMED");
    const elapsed = Date.now() - started;
    value.checked_at = new Date(serverTime + elapsed).toISOString();
    value.stages[4].status = elapsed < 5000 ? "ACTIVE" : "EXPIRED";
    value.stages[4].facts = {
      expires_at: new Date(serverTime + 5000).toISOString(),
    };
    return value;
  });
  render(<DispatchOverview />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Pickup journey for TT-CN-ONE" }),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4000);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(999);
  });
  expect(screen.getByText("active")).toBeInTheDocument();
  expect(
    vi
      .mocked(tradeRequest)
      .mock.calls.filter(([path]) => path.includes("dispatch-journey")),
  ).toHaveLength(2);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(screen.getByText("expired")).toBeInTheDocument();
  expect(screen.queryByText("active")).not.toBeInTheDocument();
  expect(
    vi
      .mocked(tradeRequest)
      .mock.calls.filter(([path]) => path.includes("dispatch-journey")),
  ).toHaveLength(3);
});
