"use client";

import { displayStatus, type Shipment } from "@/lib/shipments";
import { statusBadgeClasses } from "./status";
import type { ShipmentDetailsState } from "@/hooks/use-shipment-details";

type Props = Pick<
  ShipmentDetailsState,
  | "regulationRules"
  | "impactAnalysis"
  | "publishingRegulation"
  | "publishDemoRegulationAndAnalyze"
> & { shipment: Shipment };

export function RegulationImpactPanel({
  shipment,
  regulationRules,
  impactAnalysis,
  publishingRegulation,
  publishDemoRegulationAndAnalyze,
}: Props) {
  return (
    <section
      id="regulations"
      className="scroll-mt-24 rounded border border-slate-200 bg-white p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">
          Regulatory Change Impact
        </h2>
        <button
          type="button"
          disabled={publishingRegulation}
          onClick={() => void publishDemoRegulationAndAnalyze()}
          className="rounded bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {publishingRegulation ? "Analyzing..." : "Publish demo policy"}
        </button>
      </div>
      <details className="mt-5 border-y border-white/10 py-3">
        <summary className="cursor-pointer font-semibold text-ink">
          Regulation versions ({regulationRules.length})
        </summary>
        <div className="mt-3 divide-y divide-white/10">
          {regulationRules
            .filter(
              (rule) =>
                !shipment.domestic ||
                rule.conditions.scope === "india_domestic",
            )
            .map((rule) => (
              <article
                key={`${rule.rule_id}-${rule.version}`}
                className="py-3 text-sm"
              >
                <p className="font-semibold">{rule.title}</p>
                <p className="mt-1 text-slate-400">
                  {rule.jurisdiction} / {rule.procedure_type} / v{rule.version}
                </p>
                <p className="mt-1 text-slate-400">
                  Effective {rule.effective_from} to{" "}
                  {rule.effective_to ?? "open-ended"}
                </p>
                <p className="mt-1">
                  Required documents:{" "}
                  {rule.required_documents.map(displayStatus).join(", ") ||
                    "None"}
                </p>
              </article>
            ))}
        </div>
      </details>
      {impactAnalysis ? (
        <div className="mt-5 space-y-3">
          {impactAnalysis.impacted_shipments.length === 0 ? (
            <p className="text-sm text-slate-600">
              No active or planned shipments were affected by the selected rule.
            </p>
          ) : (
            impactAnalysis.impacted_shipments.map((impact) => (
              <article
                key={`${impact.shipment_id}-${impact.triggering_regulation.id}`}
                className="rounded border border-slate-200 p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-slate-950">
                      {impact.shipment_reference}
                    </h3>
                    <p className="mt-1 text-sm text-slate-600">
                      {impact.triggering_regulation.title}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <span
                      className={statusBadgeClasses(impact.previous_status)}
                    >
                      Was {displayStatus(impact.previous_status)}
                    </span>
                    <span className={statusBadgeClasses(impact.new_status)}>
                      Now {displayStatus(impact.new_status)}
                    </span>
                  </div>
                </div>
                <p className="mt-3 text-sm text-slate-700">
                  {impact.corrective_action}
                </p>
                {impact.route_recommendation ? (
                  <p className="mt-3 rounded bg-teal-50 p-3 text-sm text-teal-900">
                    Alternate route: {impact.route_recommendation.label}
                  </p>
                ) : null}
              </article>
            ))
          )}
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-600">
          Publish a demo interstate packing-list policy to find affected active
          and planned shipments.
        </p>
      )}
    </section>
  );
}
