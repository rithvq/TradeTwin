import { existsSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MobileModuleGrid } from "@/components/dashboard/mobile-module-grid";
import { TradeTwinOrbitalDashboard } from "@/components/dashboard/tradetwin-orbital-dashboard";
import { TooltipProvider } from "@/components/ui/tooltip";
import { fetchDashboardSummary } from "@/lib/api/dashboard";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";
import type { DashboardSummaryData } from "@/types/dashboard";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const summary: DashboardSummaryData = {
  platformStatus: "operational",
  activeShipments: 12,
  highRiskShipments: 2,
  pendingReviews: 6,
  complianceAlerts: 3,
  regulationChanges: 1,
  missingDocuments: 4,
  graphRelationships: 148,
  routeAlternatives: 5,
  serviceHealth: [],
  dataSource: "mock",
  mockFields: ["pendingReviews"],
  refreshedAt: "2026-09-08T10:00:00.000Z",
};

function renderDashboard() {
  return render(
    <TooltipProvider>
      <TradeTwinOrbitalDashboard modules={tradeTwinModules} summary={summary} />
    </TooltipProvider>,
  );
}

describe("TradeTwin orbital dashboard", () => {
  beforeEach(() => {
    push.mockReset();
  });

  it("renders all eight TradeTwin module nodes", () => {
    renderDashboard();

    expect(tradeTwinModules).toHaveLength(8);
    for (const dashboardModule of tradeTwinModules) {
      expect(
        screen.getByRole("button", { name: `Open ${dashboardModule.title} details` }),
      ).toBeInTheDocument();
    }
    expect(
      screen.queryByRole("button", { name: "Return to TradeTwin dashboard overview" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Select a module to inspect actions")).not.toBeInTheDocument();
  });

  it("opens a module panel and navigates to the correct destination", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: "Open Shipment Twin details" }));
    const panel = screen.getByLabelText("Shipment Twin details");
    expect(panel).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: /open module/i }));
    expect(push).toHaveBeenCalledWith("/dashboard/shipments");
  });

  it("highlights related nodes and fades unrelated nodes", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: "Open Shipment Twin details" }));

    expect(screen.getByRole("button", { name: "Open Documents details" })).toHaveAttribute(
      "data-related",
      "true",
    );
    expect(screen.getByRole("button", { name: "Open Compliance details" })).toHaveAttribute(
      "data-related",
      "true",
    );
    expect(screen.getByRole("button", { name: "Open Risk Intelligence details" })).toHaveClass(
      "opacity-70",
    );
  });

  it("closes the selected panel when Escape is pressed", async () => {
    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: "Open Compliance details" }));
    expect(screen.getByLabelText("Compliance details")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByLabelText("Compliance details")).not.toBeInTheDocument();
  });

  it("moves keyboard focus between adjacent nodes", () => {
    renderDashboard();
    const shipmentNode = screen.getByRole("button", { name: "Open Shipment Twin details" });
    const documentsNode = screen.getByRole("button", { name: "Open Documents details" });

    shipmentNode.focus();
    fireEvent.keyDown(shipmentNode, { key: "ArrowRight" });
    expect(documentsNode).toHaveFocus();
  });

  it("keeps every feature on one orbit and continues rotating on pointer entry", () => {
    const { container } = renderDashboard();
    const orbitTrack = screen.getByTestId("orbit-track");
    const nodePositions = container.querySelectorAll(".tt-orbit-node-position");
    const uprightAnchors = container.querySelectorAll(
      ".tt-orbit-node-position > .tt-orbit-node-upright > .tt-orbit-node-anchor",
    );

    expect(screen.getAllByTestId("main-orbit")).toHaveLength(1);
    expect(screen.getAllByTestId("orbit-center")).toHaveLength(1);
    expect(screen.getByTestId("orbit-center")).toHaveAttribute("aria-hidden", "true");
    expect(nodePositions).toHaveLength(tradeTwinModules.length);
    expect(uprightAnchors).toHaveLength(tradeTwinModules.length);
    for (const nodePosition of nodePositions) {
      expect(nodePosition.getAttribute("style")).toContain(
        "translateX(var(--tt-orbit-radius))",
      );
    }

    fireEvent.mouseEnter(screen.getByTestId("orbit-stage"));
    expect(orbitTrack).toHaveAttribute("data-auto-rotate", "true");
  });

  it("uses a full-width viewport-sized desktop workspace", () => {
    renderDashboard();

    expect(screen.getByTestId("dashboard-shell")).toHaveClass(
      "tt-dashboard-shell",
      "w-full",
    );
    expect(screen.getByTestId("dashboard-shell")).not.toHaveClass("max-w-[1500px]");
    expect(screen.getByTestId("dashboard-workspace")).toHaveClass(
      "tt-dashboard-workspace",
      "md:grid",
    );
  });

  it("disables automatic rotation for reduced-motion users", () => {
    vi.mocked(window.matchMedia).mockImplementation((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    renderDashboard();
    expect(screen.getByTestId("orbit-track")).toHaveAttribute("data-auto-rotate", "false");
  });

  it("renders a complete mobile module grid", () => {
    render(
      <TooltipProvider>
        <MobileModuleGrid modules={tradeTwinModules} />
      </TooltipProvider>,
    );

    expect(screen.getByTestId("mobile-module-grid")).toBeInTheDocument();
    for (const dashboardModule of tradeTwinModules) {
      expect(screen.getByRole("heading", { name: dashboardModule.title })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("link", { name: /open module/i })).toHaveLength(8);
  });
});

describe("dashboard data adapter", () => {
  it("returns a usable, explicitly marked fallback when APIs fail", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));

    const result = await fetchDashboardSummary();

    expect(result.dataSource).toBe("mock");
    expect(result.activeShipments).toBe(12);
    expect(result.mockFields).toContain("graphRelationships");
    expect(result.serviceHealth.every((service) => service.status === "unavailable")).toBe(true);
  });
});

describe("route preservation", () => {
  it("keeps existing TradeTwin routes and adds all dashboard routes", () => {
    const routes = [
      "app/page.tsx",
      "app/shipments/[id]/page.tsx",
      "app/shipments/[id]/documents/page.tsx",
      "app/dashboard/page.tsx",
      "app/dashboard/shipments/page.tsx",
      "app/dashboard/shipments/new/page.tsx",
      "app/dashboard/documents/page.tsx",
      "app/dashboard/compliance/page.tsx",
      "app/dashboard/graph/page.tsx",
      "app/dashboard/risk/page.tsx",
      "app/dashboard/optimizer/page.tsx",
      "app/dashboard/regulations/page.tsx",
      "app/dashboard/evidence/page.tsx",
      "app/dashboard/reports/page.tsx",
    ];

    for (const route of routes) {
      expect(existsSync(resolve(process.cwd(), route)), route).toBe(true);
    }
  });
});
