import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCommercialDraft } from "@/hooks/use-commercial-draft";
import { TradeApiError, type Trade } from "@/lib/trades";
import { TradeWizard } from "@/components/trades/wizard";

const request = vi.hoisted(() => vi.fn());
vi.mock("@/lib/trades", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/trades")>()),
  tradeRequest: request,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/trades/trade-context", () => ({
  useTradeContext: () => ({
    org: "org",
    role: "SELLER",
    refs: { states: [], units: [] },
  }),
}));
const view: Trade = {
  execution_mode: "PRODUCTION",
  trade_id: "trade",
  reference: "TT-DRAFT",
  agreement_status: "DRAFT",
  etag: '"1"',
  current_revision_id: "revision1",
  revision_number: 1,
  accepted_revision: null,
  current_candidate_revision: {
    id: "revision1",
    revision_number: 1,
    revision_kind: "DRAFT",
    terms_hash: "a".repeat(64),
    facts: { seller_organization_id: "org", tax_terms: "Initial", items: [] },
    pricing_summary: {},
    created_at: "2026-10-11T00:00:00Z",
  },
  active_offer: null,
  pending_amendment: null,
  approval_progress: [],
  pricing_summary: {},
  next_actions: ["EDIT_DRAFT", "PUBLISH"],
  validation_errors: [],
  dispatch_readiness: "NOT_ASSESSED",
};

beforeEach(() => {
  request.mockReset();
  request.mockImplementation(async (path: string) =>
    path.startsWith("/organizations")
      ? { legal_name: "Business", registrations: [] }
      : path.startsWith("/trading-partners")
        ? { items: [] }
        : view,
  );
});
afterEach(() => {
  vi.useRealTimers();
});

describe("commercial autosave", () => {
  it("does not expose editable inputs before the saved revision has loaded", async () => {
    let resolveTrade!: (trade: Trade) => void;
    request.mockImplementation(async (path: string) =>
      path === "/trades/trade"
        ? new Promise<Trade>((resolve) => {
            resolveTrade = resolve;
          })
        : path.startsWith("/organizations")
          ? { legal_name: "Business", registrations: [] }
          : { items: [] },
    );
    render(<TradeWizard tradeId="trade" />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading the saved candidate",
    );
    expect(
      screen.queryByRole("button", { name: /Save draft/i }),
    ).not.toBeInTheDocument();
    await act(async () => {
      resolveTrade(view);
    });
    expect(
      await screen.findByRole("button", { name: /Save draft/i }),
    ).toBeInTheDocument();
  });
  it("uses the actual trade participant role when an interface filter differs", async () => {
    const { result } = renderHook(() =>
      useCommercialDraft("trade", "org", "BUYER"),
    );
    await waitFor(() => expect(result.current.trade?.trade_id).toBe("trade"));
    expect(result.current.role).toBe("SELLER");
    expect(
      request.mock.calls.filter(([path]) => path === "/trades/trade"),
    ).toHaveLength(1);
  });
  it("saves an incomplete draft without manufacturing required fields", async () => {
    const { result } = renderHook(() =>
      useCommercialDraft(undefined, "org", "SELLER"),
    );
    await act(async () => {
      await result.current.save();
    });
    const call = request.mock.calls.find(([path]) => path === "/trades")!;
    expect(call[3].facts.items[0].description).toBeNull();
    expect(call[3].facts.seller_organization_id).toBe("org");
    expect(call[3].facts).not.toHaveProperty("terms_hash");
    expect(call[3].facts).not.toHaveProperty("agreement_status");
  });
  it("blocks stale autosaves and retains local changes rather than silently overwriting", async () => {
    const { result } = renderHook(() =>
      useCommercialDraft("trade", "org", "SELLER"),
    );
    await waitFor(() => expect(result.current.trade).not.toBeNull());
    request.mockRejectedValueOnce(
      new TradeApiError(
        "REVISION_MISMATCH",
        "Reload the current revision",
        [],
        412,
      ),
    );
    await act(async () => {
      result.current.change({
        ...result.current.facts,
        tax_terms: "Local edit",
      });
    });
    await act(async () => {
      await result.current.save();
    });
    expect(result.current.conflict).toBe(true);
    expect(result.current.facts.tax_terms).toBe("Local edit");
    const count = request.mock.calls.length;
    await act(async () => {
      await result.current.save();
    });
    expect(request.mock.calls.length).toBe(count);
  });
  it("publishes only a saved candidate with its current ETag, never an implicit approval", async () => {
    const { result } = renderHook(() =>
      useCommercialDraft("trade", "org", "SELLER"),
    );
    await waitFor(() => expect(result.current.trade).not.toBeNull());
    await act(async () => {
      result.current.change({
        ...result.current.facts,
        commercial_terms: { commercial_valid_until: "2026-11-01T00:00:00Z" },
      });
    });
    request.mockImplementation(async (path: string) =>
      path.endsWith("/draft")
        ? { ...view, etag: '"2"', current_revision_id: "revision2" }
        : { ...view, active_offer: { id: "offer" } },
    );
    await act(async () => {
      await result.current.publish();
    });
    const call = request.mock.calls.find(([path]) => path.endsWith("/offers"))!;
    expect(call[3].revision_id).toBe("revision2");
    expect(call[4]).toBe('"2"');
    expect(
      request.mock.calls.some(([path]) => path.endsWith("/confirmations")),
    ).toBe(false);
  });
});
