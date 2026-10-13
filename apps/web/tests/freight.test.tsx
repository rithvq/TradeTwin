import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  freightMoney,
  type FreightContext,
  type FreightRun,
  type FreightScenario,
} from "@/lib/freight";
import { FreightComparison } from "@/components/freight/comparison";

const action = vi.hoisted(() => vi.fn());
const fixture = vi.hoisted(() => ({ data: null as unknown }));
vi.mock("@/components/trades/trade-context", () => ({
  useTradeContext: () => ({ org: "payer" }),
}));
vi.mock("@/hooks/use-operations", () => ({
  useOperationsResource: () => ({
    data: fixture.data,
    error: "",
    reload: vi.fn(),
  }),
  useOperationalMutation: () => ({ run: action, pending: false }),
}));
const context = {
  consignment_id: "cn",
  capabilities: ["tradetwin.selection.prepare"],
  current_assignment_id: "old",
  expected_consignment_row_version: 1,
  compliance_context_version: 2,
  consignment_etag: '"1"',
} as FreightContext;
const base: FreightScenario = {
  scenario_code: "BASE",
  planning_outcome: "SUPPORTED_PLAN",
  ranking_eligibility: "RANKABLE",
  estimated_departure_at: "2026-10-13T09:00:00Z",
  estimated_arrival_at: "2026-10-13T15:30:00Z",
  estimated_completion_at: "2026-10-13T15:30:00Z",
  route: {
    distance_meters: 360000,
    estimated_driving_seconds: 21600,
    state_sequence: ["29", "33"],
    data_provenance: { source_reference: "Synthetic retained dataset" },
  },
  cost: {
    carrier_payable_minor: "1890000",
    external_cost_minor: "0",
    recipient_tax_cash_estimate_minor: "0",
    scenario_contingent_charge_minor: "0",
    comparison_total_minor: "1890000",
    known_partial_subtotal_minor: "1890000",
    cost_completeness: "COMPLETE_FOR_COMPARISON",
    price_basis: "QUOTED_FIXED",
    unknown_cost_categories: [],
    calculation_steps: [],
  },
  why_excluded: [],
  planning_constraint_results: [],
  candidate_compliance_results: [],
  post_selection_actions: ["FRESH_PHASE4_EVALUATION"],
  informational_limitations: ["Static travel-time estimate, not a guarantee."],
};
function data() {
  const run: FreightRun = {
    id: "run",
    input_hash: "hash",
    result_hash: "result",
    job_state: "COMPLETED",
    execution_mode: "SIMULATION",
    freshness: "CURRENT",
    price_visible: true,
    evaluated_as_of: "2026-10-13T09:00:00Z",
    candidates: [
      {
        candidate_id: "candidate",
        candidate_hash: "candidate-hash",
        quote_revision_id: "quote",
        quote_hash: "quote-hash",
        carrier_organisation_id: "carrier",
        vehicle_id: "vehicle",
        offer_label: "A",
        scenarios: {
          BASE: structuredClone(base),
          EXTRA_WAIT: { ...structuredClone(base), scenario_code: "EXTRA_WAIT" },
        },
      },
    ],
    rankings: {
      BASE: {
        LOWEST_COMPARABLE_COST: [
          {
            candidate_id: "candidate",
            rank: 1,
            pareto_member: true,
            explanation: "Lowest comparable outlay among these candidates.",
          },
        ],
      },
    },
  };
  fixture.data = run;
  return run;
}
describe("Freight comparison boundaries", () => {
  it("formats exact large integer paise without floating-point money", () => {
    expect(freightMoney("900719925474099399")).toBe(
      "INR 9,00,71,99,25,47,40,993.99",
    );
    expect(freightMoney(null)).toBe("Incomplete");
    expect(freightMoney("0")).toBe("INR 0.00");
  });
  it("shows source, route and separate comparable amounts", () => {
    data();
    render(
      <FreightComparison runId="run" context={context} reload={vi.fn()} />,
    );
    expect(
      screen.getByRole("table", { name: "Freight candidate comparison" }),
    ).toBeVisible();
    expect(screen.getByText("29 > 33")).toBeVisible();
    expect(screen.getAllByText("INR 18,900.00")).toHaveLength(2);
    expect(screen.getByText("Rank 1 / Pareto")).toBeVisible();
  });
  it("never enables commitment of a stress scenario", () => {
    data();
    render(
      <FreightComparison runId="run" context={context} reload={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText("Scenario"), {
      target: { value: "EXTRA_WAIT" },
    });
    expect(screen.getByRole("button", { name: "Propose" })).toBeDisabled();
  });
  it("does not display price ordering for a price-masked user", () => {
    const run = data();
    run.price_visible = false;
    delete run.rankings;
    delete run.candidates[0].scenarios.BASE.cost;
    render(
      <FreightComparison runId="run" context={context} reload={vi.fn()} />,
    );
    expect(screen.queryByText("Carrier quote")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Objective")).not.toBeInTheDocument();
    expect(screen.queryByText("Rank 1 / Pareto")).not.toBeInTheDocument();
  });
  it("blocks a stale proposal and preserves its historical comparison", () => {
    const run = data();
    run.freshness = "STALE";
    render(
      <FreightComparison runId="run" context={context} reload={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Propose" })).toBeDisabled();
    expect(screen.getByText(/Historical comparison/)).toBeVisible();
  });
  it("sends exact hashes and current versions without changing trade terms", () => {
    data();
    render(
      <FreightComparison runId="run" context={context} reload={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    expect(action).toHaveBeenCalledWith(
      "/consignments/cn/tradetwin-selections",
      {
        run_id: "run",
        candidate_id: "candidate",
        candidate_hash: "candidate-hash",
        quote_revision_id: "quote",
        quote_hash: "quote-hash",
        scenario_code: "BASE",
        expected_existing_assignment_id: "old",
        expected_consignment_row_version: 1,
        expected_context_version: 2,
      },
      '"1"',
    );
  });
});
