import { afterEach, describe, expect, it, vi } from "vitest";

import { complianceFetchBlob } from "@/lib/compliance";
import { documentFetch } from "@/lib/documents";
import { getLatestRiskAssessment, intelligenceFetch } from "@/lib/intelligence";
import { apiFetch, deleteShipment } from "@/lib/shipments";

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

describe("service HTTP transport", () => {
  it("preserves Headers instances and caller-provided content types", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}"));
    await apiFetch("/shipments", {
      headers: new Headers({
        "X-Request-Id": "test",
        "Content-Type": "application/custom+json",
      }),
    });
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.get("X-Request-Id")).toBe("test");
    expect(headers.get("Content-Type")).toBe("application/custom+json");
  });

  it("allows the browser to supply the multipart boundary for document uploads", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response('{"id":"doc"}'));
    const body = new FormData();
    body.append("document_type", "tax_invoice");
    await documentFetch("/shipments/id/documents", { method: "POST", body });
    expect(
      new Headers(fetchMock.mock.calls[0][1]?.headers).has("Content-Type"),
    ).toBe(false);
    expect(fetchMock.mock.calls[0][1]?.body).toBe(body);
  });

  it("does not parse an empty shipment deletion response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );
    await expect(deleteShipment("id")).resolves.toBeUndefined();
  });

  it("preserves report bytes and explicit authorization headers", async () => {
    window.sessionStorage.setItem("tradetwin-token", "fallback-token");
    const report = new Blob(["%PDF-report"], { type: "application/pdf" });
    const response = new Response(null, {
      headers: { "Content-Type": "application/pdf" },
    });
    const readBlob = vi.spyOn(response, "blob").mockResolvedValue(report);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    const blob = await complianceFetchBlob(
      "/reports/compliance/id?format=pdf",
      {
        headers: { Authorization: "Bearer explicit-token" },
      },
    );
    expect(blob).toBe(report);
    expect(blob.size).toBe(11);
    expect(blob.type).toBe("application/pdf");
    expect(readBlob).toHaveBeenCalledOnce();
    expect(
      new Headers(fetchMock.mock.calls[0][1]?.headers).get("Authorization"),
    ).toBe("Bearer explicit-token");
  });

  it("treats a missing risk assessment as an empty state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("not found", { status: 404 }),
    );
    await expect(getLatestRiskAssessment("id")).resolves.toBeNull();
  });

  it("does not turn other risk-service errors into an empty state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("offline", { status: 503 }),
    );
    await expect(getLatestRiskAssessment("id")).rejects.toThrow("offline");
  });

  it("preserves upstream errors and supplies a fallback for empty error bodies", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockResolvedValueOnce(
      new Response("invalid shipment", { status: 422 }),
    );
    await expect(apiFetch("/shipments")).rejects.toThrow("invalid shipment");
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));
    await expect(
      intelligenceFetch("/intelligence/hs-classify"),
    ).rejects.toThrow("Request failed with 502");
  });
});
