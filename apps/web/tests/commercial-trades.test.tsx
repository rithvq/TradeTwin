import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TradeArea } from "@/components/trades/trade-context";
import { TradeWorkspace } from "@/components/trades/trade-workspace";
import {
  editableFacts,
  displayMoney,
  tradeRequest,
  TradeApiError,
  type Trade,
} from "@/lib/trades";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

describe("commercial API and exact presentation", () => {
  it("forwards scoped concurrency and idempotency headers without converting paise to floats", async () => {
    const request = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ trade_id: "id" }), { status: 201 }),
      );
    await tradeRequest(
      "/trades",
      "org",
      "POST",
      { quantity: "10.000000" },
      '"2"',
      "retry-key",
    );
    const options = request.mock.calls[0][1]!;
    const headers = new Headers(options.headers);
    expect(headers.get("If-Match")).toBe('"2"');
    expect(headers.get("X-Organization-Id")).toBe("org");
    expect(headers.get("Idempotency-Key")).toBe("retry-key");
    expect(displayMoney("124500")).toBe("INR 1,245.00");
    expect(displayMoney("9223372036854775807")).toContain(".07");
    request.mockRestore();
  });
  it("preserves field paths and conflict codes for draft errors", async () => {
    const request = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "REVISION_MISMATCH",
            message: "Reload",
            field_errors: [
              {
                path: "items.0.quantity",
                code: "INVALID",
                message: "Positive quantity required",
              },
            ],
          },
        }),
        { status: 412 },
      ),
    );
    await expect(
      tradeRequest("/trades/id/draft", "org", "PATCH", {}),
    ).rejects.toMatchObject({
      code: "REVISION_MISMATCH",
      status: 412,
      fields: [{ path: "items.0.quantity" }],
    });
    request.mockRestore();
  });
  it("strips derived fields from a saved revision while retaining stable line references", () => {
    const values = editableFacts({
      initiated_by_role: "SELLER",
      bill_from: {
        legal_name: "Snapshot",
        organization_id: "org",
        billing_address: {},
      },
      items: [
        {
          line_ref: "stable",
          line_no: 1,
          quantity: "10.000000",
          line_quoted_total_minor: "125000",
        },
      ],
    });
    expect(values).toEqual({
      bill_from: { organization_id: "org", billing_address: {} },
      items: [{ line_ref: "stable", quantity: "10.000000" }],
    });
    expect(new TradeApiError("FORBIDDEN", "No approval").message).toBe(
      "No approval",
    );
  });
});

it("shows accepted agreement separately, never fabricates future module results or approval buttons", async () => {
  const revision = {
    id: "accepted",
    revision_number: 2,
    revision_kind: "INITIAL_OFFER",
    terms_hash: "a".repeat(64),
    created_at: "2026-10-11T00:00:00Z",
    facts: { items: [] },
    pricing_summary: {
      quoted_goods_total_minor: "124500",
      complete_tax_estimate_minor: null,
    },
  };
  const trade: Trade = {
    execution_mode: "PRODUCTION",
    trade_id: "trade",
    reference: "TT-COM",
    agreement_status: "CONFIRMED",
    etag: '"4"',
    current_revision_id: "candidate",
    revision_number: 3,
    accepted_revision: revision,
    current_candidate_revision: {
      ...revision,
      id: "candidate",
      revision_number: 3,
    },
    active_offer: null,
    pending_amendment: {
      id: "amendment",
      status: "DRAFT",
      reason: "Change",
      proposer_organization_id: "org",
    },
    approval_progress: [],
    pricing_summary: {},
    next_actions: [],
    validation_errors: [],
    dispatch_readiness: "NOT_ASSESSED",
  };
  const request = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input) => {
      const path = String(input);
      const result = path.endsWith("/me")
        ? {
            user: { id: "user", display_name: "Member" },
            memberships: [
              {
                organization_id: "org",
                legal_name: "Business",
                capabilities: ["ORG_ADMIN"],
                registrations: [],
                permissions: [],
              },
            ],
          }
        : path.endsWith("/reference-data")
          ? { states: {}, unit_codes: [], capability_permissions: {} }
          : path.endsWith("/evidence-events")
            ? { items: [], next_cursor: null }
            : trade;
      return new Response(JSON.stringify(result));
    });
  render(
    <TradeArea>
      <TradeWorkspace tradeId="trade" />
    </TradeArea>,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Accepted commercial agreement" }),
    ).toBeInTheDocument(),
  );
  expect(
    screen.getByRole("heading", { name: "Pending amendment (not yet agreed)" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Dispatch readiness: Not assessed"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Accept offered terms" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Risk" }));
  expect(
    screen.getByText(/No shipment execution is linked/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Open existing risk module" }),
  ).toHaveAttribute("href", "/dashboard/risk");
  request.mockRestore();
});
