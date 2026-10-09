import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "@/app/api/services/[service]/[...path]/route";
import { complianceHeaders } from "@/lib/compliance";

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

describe("service proxy", () => {
  it("rejects missing sessions and cross-site writes before contacting services", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const context = { params: Promise.resolve({ service: "shipment", path: ["shipments"] }) };
    const anonymous = await GET(new NextRequest("http://localhost/api/services/shipment/shipments"), context);
    expect(anonymous.status).toBe(401);
    const crossSite = await POST(new NextRequest("http://localhost/api/services/shipment/shipments", {
      method: "POST", headers: { Cookie: "tt_session=valid", Origin: "https://attacker.invalid" },
    }), context);
    expect(crossSite.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("forwards bearer credentials and report query parameters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("%PDF-demo", { headers: { "content-type": "application/pdf" } }),
    );
    const response = await GET(new NextRequest("http://localhost/api/services/compliance/reports/compliance/id?format=pdf", {
      headers: { Cookie: "tt_session=viewer-token", Authorization: "Bearer forged-token" },
    }), { params: Promise.resolve({ service: "compliance", path: ["reports", "compliance", "id"] }) });
    expect(fetchMock.mock.calls[0][0]).toContain("/reports/compliance/id?format=pdf");
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("Authorization")).toBe("Bearer viewer-token");
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(await response.text()).toBe("%PDF-demo");
  });

  it("preserves empty deletion responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    const response = await DELETE(new NextRequest("http://localhost/api/services/shipment/shipments/id", { method: "DELETE", headers: { Cookie: "tt_session=viewer-token", Origin: "http://localhost:3000" } }), {
      params: Promise.resolve({ service: "shipment", path: ["shipments", "id"] }),
    });
    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
  });

  it("returns a recoverable error when an upstream is offline", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    const response = await POST(new NextRequest("http://localhost/api/services/document/documents/id/extract", { method: "POST", headers: { Cookie: "tt_session=viewer-token", Origin: "http://localhost:3000" } }), {
      params: Promise.resolve({ service: "document", path: ["documents", "id", "extract"] }),
    });
    expect(response.status).toBe(503);
  });

  it("does not proxy arbitrary service names", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const response = await GET(new NextRequest("http://localhost/api/services/unknown/health"), {
      params: Promise.resolve({ service: "unknown", path: ["health"] }),
    });
    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

it("uses the signed-in session token for compliance requests", () => {
  window.sessionStorage.setItem("tradetwin-token", "operator-token");
  expect(complianceHeaders().get("Authorization")).toBe("Bearer operator-token");
});
