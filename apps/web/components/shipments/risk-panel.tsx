"use client";

import type { Shipment } from "@/lib/shipments";
import type { ShipmentDetailsState } from "@/hooks/use-shipment-details";

type Props = Pick<
  ShipmentDetailsState,
  "riskAssessment" | "scoringRisk" | "scoreRisk"
> & { shipment: Shipment };

export function RiskPanel({
  shipment,
  riskAssessment,
  scoringRisk,
  scoreRisk,
}: Props) {
  return (
    <section
      id="risk"
      className="scroll-mt-24 rounded border border-slate-200 bg-white p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">Risk Dashboard</h2>
        <button
          type="button"
          disabled={scoringRisk}
          onClick={() => void scoreRisk()}
          className="rounded bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {scoringRisk ? "Scoring..." : "Generate risk score"}
        </button>
      </div>
      <p className="mt-4 rounded bg-amber-50 p-3 text-sm font-medium text-amber-900">
        Prototype prediction based on synthetic or organization-provided data.
      </p>
      {riskAssessment ? (
        <div className="mt-5 space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <RiskMetric
              label={
                shipment.domestic
                  ? "Review likelihood (synthetic)"
                  : "Inspection"
              }
              value={`${Math.round(riskAssessment.inspection_probability * 100)}%`}
            />
            <RiskMetric
              label={
                shipment.domestic
                  ? "Exception likelihood (synthetic)"
                  : "Rejection"
              }
              value={`${Math.round(riskAssessment.rejection_probability * 100)}%`}
            />
            <RiskMetric
              label={shipment.domestic ? "Handling delay (synthetic)" : "Delay"}
              value={`${riskAssessment.expected_clearance_delay_hours}h`}
            />
            <RiskMetric label="Level" value={riskAssessment.risk_level} />
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {riskAssessment.risk_factors.map((factor) => (
              <article
                key={factor.factor}
                className="rounded border border-slate-200 p-3"
              >
                <p className="text-sm font-semibold text-slate-950">
                  {factor.factor}
                </p>
                <p className="mt-1 text-xs font-medium text-slate-500">
                  {factor.impact}
                </p>
                <p className="mt-2 text-sm text-slate-700">
                  {factor.explanation}
                </p>
              </article>
            ))}
          </div>
          <p className="text-xs text-slate-500">
            Model: {riskAssessment.model_version} -{" "}
            {new Date(riskAssessment.created_at).toLocaleString()}
          </p>
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-600">
          No risk assessment generated yet.
        </p>
      )}
    </section>
  );
}

function RiskMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}
