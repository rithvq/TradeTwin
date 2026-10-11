"use client";

import { displayStatus } from "@/lib/shipments";
import { statusBadgeClasses } from "./status";
import type { ShipmentDetailsState } from "@/hooks/use-shipment-details";

type Props = Pick<ShipmentDetailsState, "latestAssessment" | "complianceError">;

export function ComplianceResultsPanel({
  latestAssessment,
  complianceError,
}: Props) {
  return (
    <section
      id="compliance"
      className="scroll-mt-24 rounded border border-slate-200 bg-white p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">
          Compliance Results
        </h2>
        {latestAssessment ? (
          <span className={statusBadgeClasses(latestAssessment.status)}>
            {displayStatus(latestAssessment.status)}
          </span>
        ) : null}
      </div>
      {complianceError ? (
        <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
          {complianceError}
        </p>
      ) : null}
      {!latestAssessment ? (
        <p className="mt-4 text-sm text-slate-600">
          Run a deterministic rules assessment to view consignment outcomes.
        </p>
      ) : (
        <div className="mt-5 space-y-4">
          {latestAssessment.result.consignment_results.map((result) => (
            <article
              key={`${result.consignment_id}-${result.jurisdiction}-${result.procedure_type}`}
              className="rounded border border-slate-200 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-950">
                    {result.product_name}
                  </h3>
                  <p className="mt-1 text-sm text-slate-600">
                    {result.jurisdiction} {displayStatus(result.procedure_type)}
                  </p>
                </div>
                <span className={statusBadgeClasses(result.status)}>
                  {displayStatus(result.status)}
                </span>
              </div>
              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                {result.applicable_rules.map((rule) => (
                  <div
                    key={rule.rule_id}
                    className="rounded border border-slate-200 p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-950">
                        {rule.title}
                      </p>
                      <span className="text-xs font-medium text-slate-500">
                        v{rule.version}
                      </span>
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      {rule.rule_id}
                    </p>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
