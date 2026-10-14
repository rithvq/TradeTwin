import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JourneyOverview } from "@/components/product/journey";
import { DecisionReplay } from "@/components/product/replay";
import { AssuranceDesk } from "@/components/product/assurance";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import type { Journey } from "@/lib/product";

vi.mock("@/components/trades/trade-context", () => ({
  useTradeContext: () => ({ org: "seller" }),
}));
vi.mock("@/hooks/use-operations", () => ({
  useOperationsResource: vi.fn(),
  useOperationalMutation: vi.fn(),
}));
const run = vi.fn();
const reload = vi.fn();
const fixture: Journey = {
  trade_id: "trade",
  trade_reference: "TT-SYNTHETIC",
  execution_mode: "SIMULATION",
  computed_at: "2026-10-14T01:00:00Z",
  source_context_version: 4,
  projection_freshness: "CURRENT",
  commercial: { agreement_status: "CONFIRMED" },
  fulfilment: {
    ordered_lines: [
      {
        trade_line_ref: "line",
        description: "Synthetic cargo",
        uqc: "NOS",
        ordered_quantity: "100",
        allocated_quantity: "100",
        dispatched_quantity: "100",
        current_net_received_quantity: "90",
        inspection_accepted_quantity: "85",
        inspection_rejected_quantity: "5",
        inspection_pending_quantity: "0",
        final_short_quantity: "10",
      },
    ],
  },
  consignments: [],
  limitations: [],
  tasks: [
    {
      task_key: "k",
      basis_hash: "basis",
      title: "Inspect received goods",
      explanation: "Receipt is not acceptance",
      module_code: "SHIPMENTS",
      priority: "ACTION_REQUIRED",
      status: "OPEN",
      actionable_by_current_user: true,
      internal_screen_target: "/shipments/consignments/cn/inspection",
      user_seen_at: null,
      user_state_etag: '"3"',
    },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useOperationsResource).mockReturnValue({
    data: fixture,
    error: "",
    reload,
  });
  vi.mocked(useOperationalMutation).mockReturnValue({
    run,
    pending: false,
    error: null,
    saved: "",
  });
});

describe("Product integration", () => {
  it("shows 100/90/85/5/10 independently without finance or a completed total", () => {
    render(<JourneyOverview tradeId="trade" module="Shipments" />);
    const table = screen.getByRole("table", {
      name: "Independent fulfilment quantities",
    });
    const row = within(table).getAllByRole("row")[1];
    for (const value of ["90", "85", "5", "10", "NOS"])
      expect(within(row).getByText(value)).toBeVisible();
    expect(screen.queryByText("Goods finance")).not.toBeInTheDocument();
    expect(screen.queryByText(/100%|fully accepted/i)).not.toBeInTheDocument();
  });
  it("acknowledges only the current task basis, never an approval", () => {
    render(<JourneyOverview tradeId="trade" module="Shipments" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Mark seen: Inspect received goods" }),
    );
    expect(run).toHaveBeenCalledWith(
      "/trades/trade/workspace-task-states",
      {
        task_key: "k",
        task_basis_hash: "basis",
        operation: "SEEN",
        reason: "Reviewed task summary",
      },
      '"3"',
    );
    expect(
      screen.getByRole("link", { name: "Open Inspect received goods" }),
    ).toHaveAttribute("href", fixture.tasks[0].internal_screen_target);
  });
  it("does not expose replay commands without the explicit permission", () => {
    const { container } = render(
      <DecisionReplay
        runId="r"
        inputHash="h"
        engineVersion="v"
        capabilities={[]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(run).not.toHaveBeenCalled();
  });
  it("binds recomputation to the retained hash and engine rather than current facts", () => {
    render(
      <DecisionReplay
        runId="r"
        inputHash="h"
        engineVersion="v"
        capabilities={["evidence.replay.request"]}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Recompute captured inputs" }),
    );
    expect(run).toHaveBeenCalledWith("/evidence/replay-requests", {
      subject_type: "TRADETWIN_RUN",
      subject_id: "r",
      replay_kind: "RECOMPUTE_CAPTURED_INPUTS",
      source_manifest_hash: "h",
      expected_engine_version: "v",
    });
  });
  it("keeps unqualified assurance visible without an activation shortcut", () => {
    vi.mocked(useOperationsResource).mockReturnValue({
      data: {
        qualification_outcome: "NOT_QUALIFIED",
        manifest: null,
        limitations: ["Recovery is unavailable"],
      },
      error: "",
      reload,
    });
    render(<AssuranceDesk capabilities={["readiness.read"]} />);
    expect(screen.getByText("Recovery is unavailable")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /activate|approve|force/i }),
    ).not.toBeInTheDocument();
  });
});
