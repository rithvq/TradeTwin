"use client";

import Link from "next/link";
import { displayStatus, type Shipment } from "@/lib/shipments";
import { statusBadgeClasses } from "./status";
import type { ShipmentDetailsState } from "@/hooks/use-shipment-details";

type Props = Pick<
  ShipmentDetailsState,
  "routeOptimization" | "optimizingRoute" | "optimizeRoute"
> & { shipment: Shipment };

export function RouteOptionsPanel({
  shipment,
  routeOptimization,
  optimizingRoute,
  optimizeRoute,
}: Props) {
  return (
    <section
      id="optimizer"
      className="scroll-mt-24 rounded border border-slate-200 bg-white p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-950">
          Route Optimization
        </h2>
        {shipment.domestic && (
          <Link
            href={`/shipments/${shipment.id}/route-memory`}
            className="text-sm font-semibold underline"
          >
            Route memory and carrier offers
          </Link>
        )}
        <button
          type="button"
          disabled={optimizingRoute}
          onClick={() => void optimizeRoute()}
          className="rounded bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {optimizingRoute ? "Optimizing..." : "Compare routes"}
        </button>
      </div>
      {routeOptimization ? (
        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {routeOptimization.options.map((option) => (
            <article
              key={option.route_id}
              className={
                option.is_recommended
                  ? "rounded border border-teal-300 bg-teal-50 p-4"
                  : "rounded border border-slate-200 p-4"
              }
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-950">
                    {option.label}
                  </h3>
                  <p className="mt-1 text-sm text-slate-600">
                    {formatRouteCountries(option.countries)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {option.is_recommended ? (
                    <span className="rounded bg-teal-700 px-2.5 py-1 text-xs font-medium text-white">
                      Recommended
                    </span>
                  ) : null}
                  <span className={routeLegalBadgeClasses(option.legal_status)}>
                    {displayStatus(option.legal_status)}
                  </span>
                </div>
              </div>
              <p className="mt-3 text-sm text-slate-700">
                {option.description}
              </p>
              <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
                <RouteFact label="Score" value={String(option.score)} />
                {!shipment.domestic && (
                  <RouteFact
                    label="Duty"
                    value={formatMoney(option.estimated_duty)}
                  />
                )}
                <RouteFact
                  label={
                    shipment.domestic ? "Route risk (unavailable)" : "Risk"
                  }
                  value={
                    shipment.domestic
                      ? "Not scored"
                      : `${Math.round(option.risk_score * 100)}%`
                  }
                />
                <RouteFact
                  label={shipment.domestic ? "Estimated driving time" : "Delay"}
                  value={`${option.estimated_delay_hours}h`}
                />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <span className={statusBadgeClasses(option.compliance_status)}>
                  {displayStatus(option.compliance_status)}
                </span>
                {!shipment.domestic && option.fta_eligible ? (
                  <span className="rounded bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-900">
                    FTA eligible
                  </span>
                ) : null}
              </div>
              {option.corrective_actions.length > 0 ? (
                <ul className="mt-3 space-y-1 text-sm text-slate-700">
                  {option.corrective_actions.slice(0, 3).map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-600">
          Review the planned domestic route and document readiness against
          alternate movements.
        </p>
      )}
    </section>
  );
}

function RouteFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-50 p-2">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function formatRouteCountries(countries: string[]): string {
  return countries.join(" to ");
}

function formatMoney(value: number): string {
  return `$${Math.round(value).toLocaleString()}`;
}

function routeLegalBadgeClasses(status: string): string {
  const base = "whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium";
  if (status === "VALID") {
    return `${base} bg-emerald-100 text-emerald-900`;
  }
  return `${base} bg-red-100 text-red-900`;
}
