import { NextRequest, NextResponse } from "next/server";

export async function middleware(request: NextRequest) {
  if (process.env.PROFILE_AUTH_ENABLED === "false") return NextResponse.next();
  const token = request.cookies.get("tt_session")?.value;
  if (token) {
    try {
      const response = await fetch(
        `${process.env.API_SERVICE_URL ?? "http://127.0.0.1:8000"}/auth/session`,
        { headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
          signal: AbortSignal.timeout(5000) },
      );
      if (response.ok) {
        const result = NextResponse.next();
        result.headers.set("Cache-Control", "private, no-store");
        return result;
      }
    } catch { /* Authentication outages keep private pages inaccessible. */ }
  }
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  matcher: ["/", "/dashboard/:path*", "/shipments/:path*"],
};
