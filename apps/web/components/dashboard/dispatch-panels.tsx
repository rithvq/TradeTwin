"use client";

import { useEffect, useRef, useState } from "react";
import { ComputationTraceDetails } from "@/components/compliance/computation-trace";
import { type DispatchJourney, dispatchLabel } from "@/lib/dispatch-dashboard";
import { tradeRequest } from "@/lib/trades";
import { DispatchFacts, DispatchStatus } from "./dispatch-panel-shared";
import { DispatchValidity } from "./dispatch-validity";

function ManifestDownload({ path, org }: { path: string; org: string }) {
  const [status, setStatus] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function download() {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setStatus("Loading evidence manifest…");
    try {
      const body = await tradeRequest<unknown>(
        path,
        org,
        "GET",
        undefined,
        undefined,
        undefined,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = "tradetwin-evidence-manifest.json";
      link.click();
      URL.revokeObjectURL(url);
      setStatus("Evidence manifest downloaded.");
    } catch {
      if (!controller.signal.aborted)
        setStatus(
          "Evidence manifest unavailable. Your current permissions are checked by the server.",
        );
    }
  }
  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => void download()}
        className="rounded-md border border-line px-3 py-2 text-sm font-semibold text-accent"
      >
        Export evidence manifest
      </button>
      {status && (
        <p role="status" className="mt-2 text-sm text-secondary">
          {status}
        </p>
      )}
    </div>
  );
}

export function DispatchPanels({
  journey,
  org,
}: {
  journey: DispatchJourney;
  org: string;
}) {
  const evidence = journey.evidence_changes;
  const snapshot = journey.stages.find((stage) => stage.number === 2);
  const movement = journey.stages.find((stage) => stage.number === 6);
  const result = journey.stages.find((stage) => stage.number === 7);
  const compliance = journey.stages.find((stage) => stage.number === 3);
  const panelClass = "rounded-lg border border-line p-4 sm:p-5";
  return (
    <div className="space-y-4">
      <article aria-labelledby="dispatch-evidence-title" className={panelClass}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 id="dispatch-evidence-title" className="font-semibold text-ink">
            1. Evidence changes
          </h4>
          <DispatchStatus value={evidence.status} />
        </div>
        <p className="mt-3 text-sm text-secondary">{evidence.notice}</p>
        {!!evidence.reason_codes.length && (
          <ul className="mt-3 space-y-1 text-sm">
            {evidence.reason_codes.map((code) => (
              <li key={code} className="capitalize">
                {dispatchLabel(code)}
              </li>
            ))}
          </ul>
        )}
        {evidence.transitions.map((transition) => (
          <p
            key={transition.document_type + transition.basis}
            className="mt-3 rounded-md border border-line bg-soft p-3 text-sm"
          >
            <strong className="capitalize">
              {dispatchLabel(transition.document_type)}
            </strong>
            : an empty evidence search gained a match{" "}
            {transition.basis === "SINCE_EVALUATION"
              ? "since this evaluation"
              : "between recorded evaluations"}
            . This does not establish accepted evidence.
          </p>
        ))}
        <ul className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
          {journey.stages[0]?.items.map((item) => (
            <li
              key={item.label}
              className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2"
            >
              <span className="font-medium">{item.label}</span>
              <DispatchStatus value={item.status} />
            </li>
          ))}
        </ul>
        {snapshot && (
          <DispatchFacts
            facts={{ captured_at: snapshot.facts.captured_at ?? null }}
          />
        )}
      </article>
      <article
        aria-labelledby="dispatch-calculation-title"
        className={panelClass}
      >
        <h4 id="dispatch-calculation-title" className="font-semibold text-ink">
          2. Rule calculation
        </h4>
        {compliance && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <span>Recorded decision</span>
            <DispatchStatus value={compliance.status} />
          </div>
        )}
        {journey.calculation ? (
          <ComputationTraceDetails trace={journey.calculation} compactRules />
        ) : (
          <p className="mt-3 text-sm">Detail not recorded.</p>
        )}
        {!!compliance?.items.length && (
          <div className="mt-4 border-t border-line pt-4 text-sm">
            <h5 className="font-semibold">Failed or unknown checks</h5>
            <ul className="mt-3 space-y-3">
              {compliance.items.map((item) => (
                <li key={item.label}>
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="capitalize">
                      {dispatchLabel(item.label)}
                    </strong>
                    <DispatchStatus value={item.status} />
                  </div>
                  {item.description && (
                    <p className="mt-1 text-secondary">{item.description}</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </article>
      <article aria-labelledby="dispatch-binding-title" className={panelClass}>
        <h4 id="dispatch-binding-title" className="font-semibold text-ink">
          3. Exact binding
        </h4>
        <p className="mt-3 text-sm text-secondary">{journey.binding.notice}</p>
        <ul className="mt-3 grid gap-3 sm:grid-cols-2">
          {journey.binding.items.map((item) => (
            <li
              key={item.label}
              className="min-w-0 rounded-md border border-line p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">{item.label}</span>
                <DispatchStatus value={item.status} />
              </div>
              {item.reference && (
                <p className="mt-2 break-words text-xs text-secondary">
                  {item.reference}
                </p>
              )}
              {!!item.reason_codes.length && (
                <p className="mt-2 text-xs capitalize">
                  {item.reason_codes.map(dispatchLabel).join(", ")}
                </p>
              )}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-secondary">
          Evidence fingerprint · SHA-256
        </p>
        <p className="mt-1 break-all font-mono text-sm">
          {String(snapshot?.facts.fingerprint_short ?? "Detail not recorded.")}
        </p>
        {journey.binding.manifest_path && (
          <ManifestDownload
            key={org + journey.binding.manifest_path}
            org={org}
            path={journey.binding.manifest_path}
          />
        )}
      </article>
      <article aria-labelledby="dispatch-movement-title" className={panelClass}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 id="dispatch-movement-title" className="font-semibold text-ink">
            4. Movement
          </h4>
          <DispatchStatus value={movement?.status ?? "PENDING"} />
        </div>
        {result && result.status !== "PENDING" && (
          <div className="mt-3 flex items-center gap-2 text-sm">
            <span>Result</span>
            <DispatchStatus value={result.status} />
          </div>
        )}
        {movement?.status === "PENDING" ? (
          <p className="mt-3 text-sm">
            Final check pending. Pickup or departure is checked in the assigned
            driver task.
          </p>
        ) : (
          <>
            {movement && <DispatchFacts facts={movement.facts} />}
            {!!result?.reason_codes.length && (
              <p className="mt-3 text-sm capitalize">
                {result.reason_codes.map(dispatchLabel).join(", ")}
              </p>
            )}
            {result && <DispatchFacts facts={result.facts} />}
          </>
        )}
        {!!journey.post_dispatch_alerts.length && (
          <div className="mt-4 rounded-md border border-line bg-soft p-3 text-sm">
            <p className="font-semibold">Post-dispatch alerts</p>
            <p className="mt-1 text-secondary">
              Investigate current conditions. The recorded movement decision is
              unchanged.
            </p>
            <ul className="mt-2 space-y-1">
              {journey.post_dispatch_alerts.map((alert) => (
                <li key={alert.code} className="capitalize">
                  {dispatchLabel(alert.code)} · {alert.severity}
                </li>
              ))}
            </ul>
          </div>
        )}
      </article>
      <DispatchValidity journey={journey} />
    </div>
  );
}
