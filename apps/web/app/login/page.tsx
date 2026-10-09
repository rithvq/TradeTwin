"use client";

import { ArrowRight, LoaderCircle, Network, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

export default function LoginPage() {
  const [provider, setProvider] = useState<{ provider: string; configured: boolean } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const reason = new URLSearchParams(window.location.search).get("error");
    if (reason === "signin") setError("Sign-in could not be completed. Please try again.");
    if (reason === "configuration") setError("Sign-in is awaiting configuration by your administrator.");
    fetch("/api/auth/providers", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error();
      setProvider(await response.json());
    }).catch(() => setError("The sign-in service is unavailable. Please try again shortly."));
  }, []);

  return (
    <main className="grid min-h-dvh place-items-center bg-canvas px-5 py-12">
      <div className="w-full max-w-md">
        <div className="mb-10 flex items-center justify-center gap-3 text-ink">
          <Network className="size-9 text-accent" aria-hidden="true" />
          <span className="text-2xl font-semibold">TradeTwin</span>
        </div>
        <section className="rounded-lg border border-line bg-surface p-7 shadow-sm sm:p-9" aria-labelledby="login-title">
          <h1 id="login-title" className="text-2xl font-semibold">Sign in to your workspace</h1>
          <p className="mt-3 text-sm leading-6 text-secondary">Your shipments, documents, and compliance evidence in one place.</p>
          {error ? <p role="alert" className="mt-5 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}
          {provider?.configured ? (
            <button type="button" onClick={() => window.location.assign("/api/auth/login")} className="mt-7 flex min-h-12 w-full items-center justify-center gap-3 rounded bg-accent px-4 py-3 text-sm font-semibold text-white hover:bg-teal-800">
              Continue with {provider.provider}<ArrowRight className="size-4" aria-hidden="true" />
            </button>
          ) : (
            <button disabled className="mt-7 flex min-h-12 w-full items-center justify-center gap-2 rounded border border-line bg-soft px-4 py-3 text-sm font-semibold text-secondary">
              {!provider && !error ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : null}
              {provider ? "Sign-in not configured" : error ? "Sign-in unavailable" : "Loading sign-in"}
            </button>
          )}
          <div className="mt-7 flex items-start gap-2 border-t border-line pt-5 text-xs leading-5 text-muted">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
            <p>Use the same account each time to return to your saved workspace.</p>
          </div>
        </section>
        <p className="mt-6 text-center text-xs text-muted">Domestic shipment compliance · India</p>
      </div>
    </main>
  );
}
