import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ComputationTrace } from "@/components/compliance/computation-trace";
import { useOperationsResource } from "@/hooks/use-operations";

vi.mock("@/components/trades/trade-context", () => ({
  useTradeContext: () => ({ org: "seller" }),
}));
vi.mock("@/hooks/use-operations", () => ({ useOperationsResource: vi.fn() }));
beforeEach(() => vi.clearAllMocks());
it("explains reuse and requires a fresh release workflow without action controls", () => {
  vi.mocked(useOperationsResource).mockReturnValue({
    data: {
      status: "RECORDED",
      strategy: "INCREMENTAL",
      authoritative_strategy: "INCREMENTAL",
      rules_total: 24,
      rules_recomputed: 5,
      rules_reused: 19,
      invalidation_reasons: ["ASSIGNMENT_CHANGED"],
      rules: [
        {
          rule_code: "VEHICLE",
          disposition: "RECOMPUTED",
          reason_codes: ["ASSIGNMENT_CHANGED"],
        },
      ],
      notice: "The new evaluation requires its own release workflow.",
    },
    error: "",
    reload: vi.fn(),
  });
  render(<ComputationTrace evaluationId="evaluation" />);
  expect(useOperationsResource).toHaveBeenCalledWith(
    "/compliance-evaluations/evaluation/computation-trace",
    "seller",
  );
  expect(screen.getByText("5 recalculated")).toBeInTheDocument();
  expect(screen.getByText("19 reused")).toBeInTheDocument();
  expect(screen.getByText(/own release workflow/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("handles unavailable and historical traces", () => {
  vi.mocked(useOperationsResource).mockReturnValue({
    data: null,
    error: "Forbidden",
    reload: vi.fn(),
  });
  const { rerender } = render(<ComputationTrace evaluationId="x" />);
  expect(screen.getByRole("alert")).toHaveTextContent("Unable to load");
  vi.mocked(useOperationsResource).mockReturnValue({
    data: {
      status: "NOT_RECORDED",
      notice: "No computation trace was retained for this evaluation.",
    },
    error: "",
    reload: vi.fn(),
  });
  rerender(<ComputationTrace evaluationId="old" />);
  expect(screen.getByText(/No computation trace/)).toBeInTheDocument();
});
