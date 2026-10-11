"use client";

import { displayStatus } from "@/lib/shipments";
import type { ShipmentDetailsState } from "@/hooks/use-shipment-details";

type Props = Pick<ShipmentDetailsState, "consistency" | "decisionError">;

export function ConsistencyPanel({ consistency, decisionError }: Props) {
  return (
    <section className="rounded border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">
          Consistency Checker
        </h2>
        {consistency ? (
          <span className="text-xs font-medium text-slate-500">
            Checked {new Date(consistency.checked_at).toLocaleString()}
          </span>
        ) : null}
      </div>
      {decisionError ? (
        <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
          {decisionError}
        </p>
      ) : null}
      {!consistency ? (
        <p className="mt-4 text-sm text-slate-600">
          Loading consistency checks...
        </p>
      ) : consistency.conflicts.length === 0 ? (
        <p className="mt-4 text-sm text-slate-600">
          No consistency conflicts found.
        </p>
      ) : (
        <div className="mt-5 space-y-3">
          {consistency.conflicts.map((conflict) => (
            <article
              key={conflict.conflict_id}
              className="rounded border border-slate-200 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-950">
                    {conflict.title}
                  </h3>
                  <p className="mt-1 text-sm text-slate-600">
                    {conflict.consignment_name ?? "Shipment level"}
                  </p>
                </div>
                <span className={severityBadgeClasses(conflict.severity)}>
                  {displayStatus(conflict.severity)}
                </span>
              </div>
              <p className="mt-3 text-sm text-slate-700">{conflict.details}</p>
              <div className="mt-3 rounded bg-slate-50 p-3 text-sm text-slate-700">
                <p className="font-medium text-slate-950">Why this matters</p>
                <p className="mt-1">{conflict.why_this_matters}</p>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function severityBadgeClasses(severity: string): string {
  const base = "whitespace-nowrap rounded px-3 py-1.5 text-sm font-medium";
  if (severity === "CRITICAL") {
    return `${base} bg-red-100 text-red-900`;
  }
  if (severity === "HIGH") {
    return `${base} bg-amber-100 text-amber-900`;
  }
  if (severity === "MEDIUM") {
    return `${base} bg-sky-100 text-sky-900`;
  }
  return `${base} bg-slate-100 text-slate-700`;
}
