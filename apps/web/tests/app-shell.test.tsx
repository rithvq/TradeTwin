import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/app-shell";
import { TooltipProvider } from "@/components/ui/tooltip";

const { apiFetchMock, pushMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
  pushMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/shipments", () => ({
  apiFetch: apiFetchMock,
}));

function renderAppShell() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AppShell>
          <div>Dashboard content</div>
        </AppShell>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("TradeTwin demo launcher", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    pushMock.mockReset();
  });

  it("prepares the seeded scenario and opens its shipment", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ id: "demo-shipment-id" });
    renderAppShell();

    await user.click(screen.getByRole("button", { name: "TradeTwin Demo" }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith("/demo/seed", { method: "POST" });
      expect(pushMock).toHaveBeenCalledWith("/shipments/demo-shipment-id");
    });
  });

  it("shows a recoverable error when the demo cannot be prepared", async () => {
    const user = userEvent.setup();
    apiFetchMock.mockRejectedValue(new Error("Shipment service unavailable"));
    renderAppShell();

    await user.click(screen.getByRole("button", { name: "TradeTwin Demo" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Shipment service unavailable",
    );
    expect(pushMock).not.toHaveBeenCalled();
  });
});
