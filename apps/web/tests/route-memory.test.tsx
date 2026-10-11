import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRouteMemory } from "@/hooks/use-route-memory";
import type { Memory } from "@/lib/state-relations";

const mocks = vi.hoisted(() => ({ shipment: vi.fn(), request: vi.fn() }));
vi.mock("@/lib/shipments", () => ({ apiFetch: mocks.shipment }));
vi.mock("@/lib/state-relations", () => ({
  stateRelationRequest: mocks.request,
}));

const origin = { city: "Chennai", state: "Tamil Nadu", pincode: "600001" };
const stop = { city: "Bengaluru", state: "Karnataka", pincode: "560001" };
const destination = { city: "Pune", state: "Maharashtra", pincode: "411001" };
const memory: Memory = {
  records: [
    { id: "offer", kind: "OFFER", recorded_at: "2026-10-11T00:00:00Z" },
  ],
  corridors: {},
  routing_configured: false,
  catalog_mode: "demo",
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  mocks.shipment.mockResolvedValue({
    id: "shipment",
    domestic: { origin, destination },
    route_legs: [
      { sequence_number: 2, domestic: { destination } },
      { sequence_number: 1, domestic: { destination: stop } },
    ],
  });
  mocks.request.mockImplementation(async (_id: string, path: string) =>
    path === "" ? memory : {},
  );
});

afterEach(() => {
  vi.useRealTimers();
});

async function load() {
  const hook = renderHook(() => useRouteMemory("shipment"));
  await act(async () => {});
  return hook;
}

describe("route memory orchestration", () => {
  it("orders stops by leg sequence and keeps reviewed offers available", async () => {
    const { result } = await load();
    expect(result.current.places).toEqual([origin, stop, destination]);
    expect(result.current.offers).toEqual(memory.records);
    act(() => result.current.placeValue(1, "latitude", "12.97"));
    expect(result.current.places[1].latitude).toBe(12.97);
  });

  it("observes and reevaluates offers with the selected history settings", async () => {
    const { result } = await load();
    act(() => {
      result.current.setTimeValue(250);
      result.current.setUseHistory(false);
    });
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(mocks.request).toHaveBeenCalledWith("shipment", "/observe", {});
    expect(mocks.request).toHaveBeenCalledWith("shipment", "/evaluate", {
      value_of_time_inr_per_hour: 250,
      use_observed_history: false,
    });
    expect(result.current.busy).toBe(false);
  });

  it("stops monitoring when disabled or unmounted", async () => {
    const { result, unmount } = await load();
    act(() => result.current.setAutoRefresh(false));
    mocks.request.mockClear();
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(mocks.request).not.toHaveBeenCalled();
    act(() => result.current.setAutoRefresh(true));
    unmount();
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("keeps failures visible and clears the pending state", async () => {
    const { result } = await load();
    await act(async () => {
      await result.current.run(async () => {
        throw new Error("Quote has expired");
      });
    });
    expect(result.current.message).toBe("Quote has expired");
    expect(result.current.busy).toBe(false);
    expect(result.current.memory).toEqual(memory);
  });
});
