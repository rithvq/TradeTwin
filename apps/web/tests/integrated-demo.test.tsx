import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { IntegratedDemoPage } from "@/components/demo-center/workspace";
import {
  activeDemo,
  enterDemo,
  exitDemo,
  type IntegratedDemo,
} from "@/lib/demo-center";

const { request, push } = vi.hoisted(() => ({
  request: vi.fn(),
  push: vi.fn(),
}));
vi.mock("@/lib/trades", () => ({ tradeRequest: request }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/components/trades/trade-context", () => ({
  TradeArea: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/dashboard/dispatch-journey", () => ({
  DispatchJourney: () => <div>Live dispatch journey</div>,
}));
vi.mock("@/components/freight-routes/result", () => ({
  FreightRouteResult: () => <div>Ordinary route comparison</div>,
}));

const fixture: IntegratedDemo = {
  id: "demo",
  status: "READY",
  expires_at: "2099-01-01T00:00:00Z",
  expired: false,
  execution_mode: "SIMULATION",
  trade_id: "trade",
  organization_id: "demo-org",
  consignment_id: "consignment",
  next_step_index: 0,
  steps: [
    {
      code: "PICKUP_RELEASE",
      label: "Review pickup evidence",
      actor: "Independent simulation reviewer",
    },
  ],
  receipts: [],
  route_study_ids: ["route"],
  sample_document_version_id: "version",
  limitations: ["Synthetic records"],
};
function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <IntegratedDemoPage id="demo" />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  request.mockReset();
  push.mockReset();
  localStorage.clear();
  sessionStorage.clear();
});

describe("integrated demo", () => {
  it("opens ordinary feature screens and queues only the registered next step", async () => {
    const user = userEvent.setup();
    request.mockResolvedValue(fixture);
    show();
    expect(
      await screen.findByRole("link", { name: /Freight & route optimizer/ }),
    ).toHaveAttribute(
      "href",
      "/shipments/trades/trade/operations?module=Optimizer",
    );
    expect(
      screen.getByRole("link", { name: /Open parsed sample PDF/ }),
    ).toHaveAttribute("href", "/documents/versions/version/processing");
    expect(
      screen.queryByRole("button", { name: "Record pickup" }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Run next demo step" }),
    );
    expect(request).toHaveBeenCalledWith(
      "/demo-sessions/demo/steps",
      undefined,
      "POST",
      { step_code: "PICKUP_RELEASE" },
    );
    await waitFor(() =>
      expect(localStorage.getItem("tt-commercial-org")).toBe("demo-org"),
    );
  });

  it("disables actions during setup and after failure", async () => {
    request.mockResolvedValue({
      ...fixture,
      status: "RUNNING",
      consignment_id: null,
      organization_id: null,
    });
    const view = show();
    expect(
      await screen.findByRole("button", { name: "Run next demo step" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("navigation", { name: "Demo features" }),
    ).not.toBeInTheDocument();
    view.unmount();
    request.mockResolvedValue({
      ...fixture,
      status: "FAILED",
      receipts: [
        {
          id: "failed",
          step_code: "SETUP",
          status: "FAILED",
          error_code: "STORAGE_UNAVAILABLE",
          result: null,
        },
      ],
    });
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "STORAGE_UNAVAILABLE",
    );
    expect(
      screen.getByRole("button", { name: "Run next demo step" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Start fresh demo" }),
    ).toBeEnabled();
  });

  it("clears status when the server cannot refresh the demo", async () => {
    request.mockRejectedValue(new Error("Current status unavailable"));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Current status unavailable",
    );
    expect(
      screen.queryByRole("button", { name: "Run next demo step" }),
    ).not.toBeInTheDocument();
  });

  it("restores the previous organisation and role across repeated and fresh demos", () => {
    localStorage.setItem("tt-commercial-org", "production-org");
    localStorage.setItem("tt-commercial-role", "BUYER");
    enterDemo("first", "first-demo-org");
    enterDemo("second", "second-demo-org");
    expect(activeDemo()?.previousOrg).toBe("production-org");
    exitDemo();
    expect(localStorage.getItem("tt-commercial-org")).toBe("production-org");
    expect(localStorage.getItem("tt-commercial-role")).toBe("BUYER");
    expect(activeDemo()).toBeNull();
  });
});
