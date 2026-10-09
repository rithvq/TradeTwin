import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ service: string; path: string[] }> };

async function proxy(request: NextRequest, context: Context) {
  const { service, path } = await context.params;
  const upstreams: Record<string, string> = {
    shipment: process.env.SHIPMENT_SERVICE_URL ?? "http://127.0.0.1:8011",
    compliance: process.env.COMPLIANCE_SERVICE_URL ?? "http://127.0.0.1:8012",
    document: process.env.DOCUMENT_SERVICE_URL ?? "http://127.0.0.1:8013",
    intelligence: process.env.INTELLIGENCE_SERVICE_URL ?? "http://127.0.0.1:8014",
    platform: process.env.API_SERVICE_URL ?? "http://127.0.0.1:8000",
  };
  if (!Object.hasOwn(upstreams, service) || path.some((part) => part === "..")) {
    return Response.json({ detail: "Service not found" }, { status: 404 });
  }
  const headers = new Headers();
  for (const name of ["content-type", "authorization"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (process.env.PROFILE_AUTH_ENABLED !== "false") {
    const token = request.cookies.get("tt_session")?.value;
    if (!token) return Response.json({ detail: "Sign in required" }, { status: 401 });
    if (!["GET", "HEAD"].includes(request.method) &&
        request.headers.get("origin") !== (process.env.APP_PUBLIC_URL ?? "http://localhost:3000")) {
      return Response.json({ detail: "Invalid request origin" }, { status: 403 });
    }
    headers.set("authorization", `Bearer ${token}`);
  }
  try {
    const response = await fetch(
      `${upstreams[service].replace(/\/$/, "")}/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`,
      {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
        cache: "no-store",
        signal: AbortSignal.timeout(60000),
      },
    );
    const resultHeaders = new Headers();
    resultHeaders.set("Cache-Control", "private, no-store");
    for (const name of ["content-type", "content-disposition", "x-trace-id"]) {
      const value = response.headers.get(name);
      if (value) resultHeaders.set(name, value);
    }
    return new Response(response.body, { status: response.status, headers: resultHeaders });
  } catch {
    return Response.json({ detail: `${service} service is unavailable` }, { status: 503 });
  }
}

export { proxy as GET, proxy as POST, proxy as DELETE };
