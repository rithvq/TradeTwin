"use client";

import { locationLabel, type Shipment } from "@/lib/shipments";
import type { ShipmentDetailsState } from "@/hooks/use-shipment-details";

type Props = Pick<
  ShipmentDetailsState,
  | "hsRecommendations"
  | "intelligenceError"
  | "classifyingConsignmentId"
  | "classifyConsignment"
> & { shipment: Shipment };

export function ClassificationPanel({
  shipment,
  hsRecommendations,
  intelligenceError,
  classifyingConsignmentId,
  classifyConsignment,
}: Props) {
  return (
    <section className="rounded border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">
          HSN-code Recommendations
        </h2>
        <span className="rounded bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
          Human review threshold 72%
        </span>
      </div>
      {intelligenceError ? (
        <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
          {intelligenceError}
        </p>
      ) : null}
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        {shipment.consignments.map((consignment) => {
          const classification = hsRecommendations[consignment.id];
          return (
            <article
              key={consignment.id}
              className="rounded border border-slate-200 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-950">
                    {consignment.product_name}
                  </h3>
                  <p className="mt-1 text-sm text-slate-600">
                    {consignment.domestic
                      ? locationLabel(consignment.domestic.destination)
                      : `${consignment.country_of_origin} to ${consignment.destination_country}`}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={classifyingConsignmentId === consignment.id}
                  onClick={() => void classifyConsignment(consignment.id)}
                  className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
                >
                  {classifyingConsignmentId === consignment.id
                    ? "Classifying..."
                    : "Recommend"}
                </button>
              </div>
              {classification ? (
                <div className="mt-4 space-y-3">
                  {classification.recommendations.map((recommendation) => (
                    <div
                      key={recommendation.hs_code}
                      className="rounded bg-slate-50 p-3"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="font-semibold text-slate-950">
                            {recommendation.hs_code} - {recommendation.title}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            {recommendation.tariff_notes}
                          </p>
                        </div>
                        <span
                          className={
                            recommendation.human_review_required
                              ? "rounded bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900"
                              : "rounded bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-900"
                          }
                        >
                          {recommendation.human_review_required
                            ? "Review"
                            : "Ready"}
                        </span>
                      </div>
                      <ConfidenceMeter value={recommendation.confidence} />
                    </div>
                  ))}
                  <p className="text-xs text-slate-500">
                    Provider: {classification.provider} - {classification.model}
                  </p>
                </div>
              ) : (
                <p className="mt-4 text-sm text-slate-600">
                  No recommendations generated yet.
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ConfidenceMeter({ value }: { value: number }) {
  const percent = Math.round(value * 100);
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between text-xs font-medium text-slate-600">
        <span>Confidence</span>
        <span>{percent}%</span>
      </div>
      <div className="mt-1 h-2 rounded bg-slate-200">
        <div
          className="h-2 rounded bg-teal-600"
          style={{ width: `${Math.max(4, Math.min(100, percent))}%` }}
        />
      </div>
    </div>
  );
}
