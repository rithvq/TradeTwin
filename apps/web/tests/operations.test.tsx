import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ActionForm, Facts } from "@/components/operations/shared";
import { EvidenceUpload } from "@/components/operations/evidence-upload";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import {
  netReversible,
  type Payment,
  type Consignment,
} from "@/lib/operations";
import { tradeRequest, TradeApiError } from "@/lib/trades";

let org = "seller";
vi.mock("@/components/trades/trade-context", () => ({
  useTradeContext: () => ({
    org,
    me: {
      memberships: [
        {
          organization_id: org,
          permissions: [{ permission_code: "attachment.upload" }],
        },
      ],
    },
  }),
}));
vi.mock("@/lib/trades", async (original) => ({
  ...(await original<typeof import("@/lib/trades")>()),
  tradeRequest: vi.fn(),
}));
beforeEach(() => {
  org = "seller";
  vi.mocked(tradeRequest).mockReset();
});

describe("Operational workflow safety", () => {
  it("renders addresses, cargo declarations and IST without raw JSON", () => {
    render(
      <Facts
        values={{
          pickup: {
            address_line1: "12 Depot Road",
            city: "Chennai",
            state_code: "33",
            country_code: "IN",
            postal_code: "600001",
          },
          cargo: { hazardous_declared: false, temperature_min_c: null },
          expected_delivery_at: "2026-10-12T00:00:00Z",
        }}
      />,
    );
    expect(screen.getByText("12 Depot Road")).toBeVisible();
    expect(screen.getByText("Chennai, 600001")).toBeVisible();
    expect(screen.getByText("India / State 33")).toBeVisible();
    expect(screen.getByText("No")).toBeVisible();
    expect(screen.getByText("Unknown")).toBeVisible();
    expect(screen.getByText(/12 Oct 2026.*5:30.*IST/)).toBeVisible();
  });

  it("scopes driver uploads to the assigned consignment with accessible labels", () => {
    render(
      <EvidenceUpload
        tradeId="trade-one"
        consignments={[{ id: "cn-one", reference: "CN-ONE" } as Consignment]}
        records={[]}
        consignmentOnly
        reload={async () => {}}
      />,
    );
    expect(screen.getByLabelText("Consignment", { exact: true })).toHaveValue(
      "cn-one",
    );
    expect(
      screen.queryByRole("option", { name: "Trade evidence" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "PAYMENT" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Purpose", { exact: true })).toHaveValue(
      "OTHER",
    );
    expect(
      screen.getByLabelText("Evidence file", { exact: true }),
    ).toHaveAttribute("type", "file");
  });

  it("retains the same idempotency key after a network error", async () => {
    vi.mocked(tradeRequest)
      .mockRejectedValueOnce(new TradeApiError("REQUEST_FAILED", "Offline"))
      .mockResolvedValueOnce({ id: "one" });
    const { result } = renderHook(() =>
      useOperationalMutation("seller", async () => {}),
    );
    await act(async () => {
      await result.current.run("/payments/one/allocations", {
        allocations: [{ amount_minor: "23" }],
      });
    });
    await act(async () => {
      await result.current.run("/payments/one/allocations", {
        allocations: [{ amount_minor: "23" }],
      });
    });
    expect(vi.mocked(tradeRequest).mock.calls[0][5]).toBe(
      vi.mocked(tradeRequest).mock.calls[1][5],
    );
    expect(result.current.saved).toBe("Recorded");
  });

  it("ignores a stale response after organisation switching", async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(tradeRequest)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValueOnce({ id: "buyer" });
    const { result, rerender } = renderHook(
      ({ selected }) =>
        useOperationsResource<{ id: string }>(
          "/trades/one/operations",
          selected,
        ),
      { initialProps: { selected: "seller" } },
    );
    rerender({ selected: "buyer" });
    await waitFor(() => expect(result.current.data?.id).toBe("buyer"));
    await act(async () => finish({ id: "seller" }));
    expect(result.current.data?.id).toBe("buyer");
  });

  it("preserves unsaved input on conflict but resets for another organisation", async () => {
    vi.mocked(tradeRequest).mockRejectedValue(
      new TradeApiError("STALE_VERSION", "Reload"),
    );
    const props = {
      name: "Record fact",
      path: "/consignments/one",
      initial: { notes: "First" },
      specs: [{ path: "notes", label: "Notes" }],
      reload: async () => {},
    };
    const { rerender } = render(<ActionForm {...props} />);
    fireEvent.change(screen.getByLabelText("Notes"), {
      target: { value: "Unsaved" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record fact" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("Notes")).toHaveValue("Unsaved");
    org = "buyer";
    rerender(<ActionForm {...props} initial={{ notes: "Buyer" }} />);
    expect(screen.getByLabelText("Notes")).toHaveValue("Buyer");
  });

  it("calculates remaining reversible paise without floating point", () => {
    const original = {
      id: "one",
      amount_minor: "9007199254740993",
      entry_type: "ALLOCATION",
      reverses_allocation_id: null,
    };
    const reversal = {
      id: "two",
      amount_minor: "23",
      entry_type: "REVERSAL",
      reverses_allocation_id: "one",
    };
    expect(
      netReversible({ allocations: [original, reversal] } as Payment, "one"),
    ).toBe("9007199254740970");
  });
});
