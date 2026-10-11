import { act, renderHook, waitFor } from "@testing-library/react";
import type { FormEvent } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useShipmentDetails } from "@/hooks/use-shipment-details";
import type { ComplianceAssessment } from "@/lib/compliance";
import type { Shipment } from "@/lib/shipments";

const mocks = vi.hoisted(() => ({
  shipment: vi.fn(),
  compliance: vi.fn(),
  risk: vi.fn(),
}));
vi.mock("@/lib/shipments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/shipments")>()),
  apiFetch: mocks.shipment,
}));
vi.mock("@/lib/compliance", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/compliance")>()),
  complianceFetch: mocks.compliance,
}));
vi.mock("@/lib/intelligence", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/intelligence")>()),
  getLatestRiskAssessment: mocks.risk,
}));

const origin = { city: "Chennai", state: "Tamil Nadu", pincode: "600001" };
const destination = { city: "Pune", state: "Maharashtra", pincode: "411001" };
const shipment: Shipment = {
  id: "shipment",
  shipment_reference: "TT-TEST",
  exporter_country: "India",
  importer_country: "India",
  transport_mode: "ROAD",
  planned_departure_at: "2026-10-12T00:00:00Z",
  planned_arrival_at: "2026-10-13T00:00:00Z",
  status: "CREATED",
  created_at: "2026-10-11T00:00:00Z",
  consignments: [],
  route_legs: [],
  domestic: {
    origin,
    destination,
    consignor_name: "Sender",
    consignee_name: "Receiver",
    movement_reason: "SUPPLY",
  },
};
const assessment: ComplianceAssessment = {
  id: "assessment",
  shipment_id: "shipment",
  job_id: null,
  status: "COMPLIANT",
  created_at: "2026-10-11T00:00:00Z",
  result: {
    shipment_id: "shipment",
    status: "COMPLIANT",
    applicable_rules: [],
    missing_documents: [],
    violations: [],
    recommended_action: "No action",
    consignment_results: [],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.shipment.mockImplementation(async (path: string) => {
    if (path.endsWith("/timeline")) return { events: [] };
    if (path.endsWith("/graph")) return { nodes: [], edges: [] };
    return shipment;
  });
  mocks.compliance.mockImplementation(async (path: string) => {
    if (path.startsWith("/compliance/evaluate/")) return assessment;
    if (path.startsWith("/consistency/check/"))
      return { conflicts: [], checked_at: "2026-10-11T00:00:00Z" };
    return [];
  });
  mocks.risk.mockResolvedValue(null);
});

describe("shipment detail actions", () => {
  it("keeps core shipment data available when optional intelligence is offline", async () => {
    mocks.risk.mockRejectedValueOnce(new Error("Intelligence offline"));
    const { result } = renderHook(() => useShipmentDetails("shipment"));
    await waitFor(() =>
      expect(result.current.intelligenceError).toBe("Intelligence offline"),
    );
    expect(result.current.shipment).toEqual(shipment);
    expect(result.current.error).toBeNull();
  });

  it("keeps uploaded-evidence and demo evaluations separate", async () => {
    const { result } = renderHook(() => useShipmentDetails("shipment"));
    await waitFor(() => expect(result.current.shipment).toEqual(shipment));
    await act(async () => {
      await result.current.evaluateCompliance(null);
    });
    expect(result.current.latestAssessment).toEqual(assessment);
    const uploadedCall = mocks.compliance.mock.calls.find(([path]) =>
      path.startsWith("/compliance/evaluate/"),
    );
    expect(JSON.parse(uploadedCall![1].body).uploaded_documents).toEqual([]);
    mocks.compliance.mockClear();
    await act(async () => {
      await result.current.evaluateCompliance(true);
    });
    const demoCall = mocks.compliance.mock.calls.find(([path]) =>
      path.startsWith("/compliance/evaluate/"),
    );
    expect(
      JSON.parse(demoCall![1].body).uploaded_documents.map(
        (doc: { document_type: string }) => doc.document_type,
      ),
    ).toEqual(["tax_invoice", "eway_bill", "packing_list"]);
    expect(result.current.evaluating).toBe(false);
  });

  it("records a domestic event with its selected location and then refreshes", async () => {
    const { result } = renderHook(() => useShipmentDetails("shipment"));
    await waitFor(() => expect(result.current.shipment).toEqual(shipment));
    const form = document.createElement("form");
    for (const [name, value] of Object.entries({
      consignment_id: "shipment",
      event_type: "LOADED",
      location: JSON.stringify(origin),
    })) {
      const input = document.createElement("input");
      input.name = name;
      input.value = value;
      form.append(input);
    }
    await act(async () => {
      await result.current.addEvent({
        currentTarget: form,
        preventDefault: vi.fn(),
      } as unknown as FormEvent<HTMLFormElement>);
    });
    const eventCall = mocks.shipment.mock.calls.find(([path]) =>
      path.endsWith("/events"),
    );
    expect(JSON.parse(eventCall![1].body)).toMatchObject({
      event_type: "LOADED",
      consignment_id: null,
      location_country: "India",
      metadata: { source: "web-ui", location: origin },
    });
    expect(result.current.submitting).toBe(false);
    expect(
      mocks.shipment.mock.calls.filter(([path]) => path.endsWith("/timeline"))
        .length,
    ).toBeGreaterThan(1);
  });
});
