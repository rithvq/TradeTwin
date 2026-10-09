import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

async function auth(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (path.length !== 1 || !["login", "callback", "session", "logout", "providers"].includes(path[0])) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }
  const origin = process.env.APP_PUBLIC_URL ?? "http://localhost:3000";
  if (request.method !== "GET" && request.headers.get("origin") !== origin) {
    return Response.json({ detail: "Invalid request origin" }, { status: 403 });
  }
  try {
    const response = await fetch(
      `${process.env.API_SERVICE_URL ?? "http://127.0.0.1:8000"}/auth/${path[0]}${request.nextUrl.search}`,
      { method: request.method, redirect: "manual", cache: "no-store",
        headers: { cookie: request.headers.get("cookie") ?? "", origin },
        signal: AbortSignal.timeout(20000) },
    );
    const headers = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "location"]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    for (const cookie of response.headers.getSetCookie()) headers.append("set-cookie", cookie);
    return new Response(response.body, { status: response.status, headers });
  } catch {
    return Response.json({ detail: "Sign-in service unavailable" }, { status: 503 });
  }
}

export { auth as GET, auth as POST };
