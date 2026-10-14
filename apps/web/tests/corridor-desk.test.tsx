import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CorridorDesk } from "@/components/corridor/desk";
import type { DynamicContext } from "@/lib/corridor";

const mocks = vi.hoisted(() => ({
  run: vi.fn(),
  reload: vi.fn(),
  data: null as DynamicContext | null,
}));
vi.mock("@/components/trades/trade-context", () => ({
  useTradeContext: () => ({ org: "org" }),
}));
vi.mock("@/hooks/use-operations", () => ({
  useOperationsResource: () => ({
    data: mocks.data,
    error: "",
    reload: mocks.reload,
  }),
  useOperationalMutation: () => ({
    run: mocks.run,
    pending: false,
    error: null,
  }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.reload.mockResolvedValue(undefined);
  mocks.data = {
    consignment_id: "cn",
    reference: "CN-1",
    execution_mode: "SIMULATION",
    movement_status: "IN_TRANSIT",
    etag: '"8"',
    dynamic_context_hash: "a".repeat(64),
    current_route_plan_revision_id: "plan",
    coverage: { status: "PARTIAL" },
    events: [],
    recovery_cases: [],
    capabilities: ["tradetwin.run"],
    impact: {
      outcome: "BLOCKED",
      items: [
        {
          event_revision_id: "event",
          headline: "Reviewed road closure",
          edge_key: "edge-one",
          outcome: "BLOCKED",
          spatial_match: "EXACT_EDGE",
          temporal_match: "OVERLAP",
          source_reference: "Official reviewed advisory",
          limitations: [],
        },
      ],
      maximum_additional_delay_seconds: null,
      limitations: ["Not a physical stop confirmation"],
    },
  };
});

describe("corridor desk", () => {
  it("shows route section, source and coverage without claiming clearance", () => {
    render(<CorridorDesk consignmentId="cn" />);
    expect(screen.getByText("Reviewed road closure")).toBeInTheDocument();
    expect(screen.getByText("edge-one")).toBeInTheDocument();
    expect(screen.getByText("Official reviewed advisory")).toBeInTheDocument();
    expect(screen.getAllByText("PARTIAL")).toHaveLength(2);
    expect(screen.queryByText("No hazard exists")).not.toBeInTheDocument();
  });
  it("reassessment submits the exact server context, route and ETag", async () => {
    mocks.run.mockResolvedValue({ id: "assessment" });
    render(<CorridorDesk consignmentId="cn" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Retain current assessment" }),
    );
    await waitFor(() =>
      expect(mocks.run).toHaveBeenCalledWith(
        "/consignments/cn/corridor-reassessments",
        {
          expected_context_hash: "a".repeat(64),
          current_route_plan_revision_id: "plan",
        },
        '"8"',
      ),
    );
  });
  it("reported driver stop is not resume or spending approval", () => {
    mocks.data!.recovery_cases = [
      {
        id: "case",
        etag: '"1"',
        status: "DETECTED",
        protection_state: "MOVEMENT_ACTION_BLOCKED",
        motion: "REPORTED_STOPPED",
        stationary_epoch: 2,
        driver_response_allowed: false,
        case_json: { reason: "Reported driver stop" },
      },
    ];
    render(<CorridorDesk consignmentId="cn" />);
    expect(screen.getByText("REPORTED_STOPPED")).toBeInTheDocument();
    expect(screen.getByText("Resume Authorised")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Resume" }),
    ).not.toBeInTheDocument();
  });
});
