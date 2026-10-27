"use client";

import { useEffect, useState } from "react";
import { useOperationsResource } from "@/hooks/use-operations";
import { useTradeContext } from "@/components/trades/trade-context";
import { displayTime, tradeRequest } from "@/lib/trades";
import {
  routeFactors,
  routeHours,
  routeWords,
  type RouteStudy,
} from "@/lib/freight-routes";
import { FreightRouteMap } from "./map";
import { FreightRouteEvidence } from "./evidence";

export function FreightRouteResult({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<RouteStudy>(
    `/freight-route-studies/${id}`,
    org,
  );
  const [chosen, setChosen] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const study = resource.data;
  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(
      () => void reload(),
      study?.result || study?.job_state === "FAILED" ? 30000 : 2000,
    );
    return () => window.clearInterval(timer);
  }, [reload, study?.result, study?.job_state]);
  if (resource.error)
    return (
      <div
        role="alert"
        className="rounded-lg border border-line bg-soft p-4 font-semibold"
      >
        <p>
          Current comparison unavailable. Refresh the comparison to confirm a
          preference.
        </p>
        <button
          type="button"
          onClick={() => void reload()}
          className="mt-3 rounded-md border border-line bg-surface px-3 py-2 text-sm"
        >
          Retry status
        </button>
      </div>
    );
  if (!study) return <p role="status">Loading route comparison…</p>;
  if (!study.result)
    return (
      <p role="status" className="rounded-lg border border-line p-4">
        {study.job_state === "FAILED"
          ? `Comparison unavailable: ${routeWords(study.error_code ?? "source unavailable")}`
          : `Fetching and checking route alternatives · ${routeWords(study.job_state)}`}
      </p>
    );
  const data = study.result,
    comparison = data.comparison;
  const best =
    study.freshness === "CURRENT" ? comparison.best_candidate_id : null;
  const active =
    data.candidates.find((c) => c.id === chosen) ||
    data.candidates.find((c) => c.id === best) ||
    data.candidates[0];
  const ranking = comparison.rankings.find(
    (r) => r.candidate_id === active?.id,
  );
  async function download() {
    try {
      const body = await tradeRequest(
        `/freight-route-studies/${id}/evidence-manifest`,
        org,
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `freight-route-comparison-${id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setDownloadError("Comparison evidence unavailable for this profile.");
    }
  }
  return (
    <section aria-label="Freight route comparison result" className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-lg font-semibold text-ink">
            {best
              ? "Preferred among compared routes"
              : "No current route preference confirmed"}
          </h4>
          <p className="mt-1 text-xs text-secondary">
            {study.source_mode} data · {study.execution_mode} trade · checked{" "}
            {study.checked_at ? displayTime(study.checked_at) : "unavailable"} ·
            valid until{" "}
            {study.valid_until ? displayTime(study.valid_until) : "unavailable"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void download()}
          className="rounded-md border border-line px-3 py-2 text-sm font-medium"
        >
          Export comparison evidence
        </button>
      </header>
      {downloadError && <p role="alert">{downloadError}</p>}
      {study.freshness !== "CURRENT" && (
        <p
          role="alert"
          className="rounded-md border border-line bg-soft p-3 font-medium"
        >
          Historical comparison. Run again with current inputs.
        </p>
      )}
      <p className="rounded-lg border border-line bg-soft p-3 text-sm">
        {comparison.notice ??
          "No route has enough comparable information to rank."}{" "}
        {comparison.comparison_status === "CONDITIONAL"
          ? "Outstanding checks require review."
          : ""}
      </p>
      {!!data.provider_failures.length && (
        <details className="rounded-lg border border-line p-3 text-sm">
          <summary className="cursor-pointer font-medium">
            Unavailable alternatives
          </summary>
          <ul className="mt-2 space-y-1">
            {data.provider_failures.map((failure, i) => (
              <li key={i}>
                {failure.variant}: {routeWords(failure.code)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {!!comparison.omitted_factors.length && (
        <p className="text-sm text-secondary">
          Not scored (incomplete evidence):{" "}
          {comparison.omitted_factors.map((f) => routeFactors[f]).join(", ")}.
          Weights redistributed across scored factors.
        </p>
      )}
      {!active ? (
        <p>No connected road alternatives were available from this source.</p>
      ) : (
        <>
          <FreightRouteMap
            routes={data.candidates}
            selected={active.id}
            best={best}
            onSelect={setChosen}
          />
          <div className="overflow-x-auto">
            <table
              aria-label="Freight route alternatives"
              className="w-full text-left text-sm"
            >
              <thead>
                <tr>
                  {[
                    "Route",
                    "Distance / travel",
                    "Toll-road exposure",
                    "Other comparison factors",
                    "Compared outcome",
                    "Why different",
                  ].map((text) => (
                    <th
                      key={text}
                      className="border-b border-line p-3 font-semibold"
                    >
                      {text}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((route, i) => {
                  const rank = comparison.rankings.find(
                    (r) => r.candidate_id === route.id,
                  );
                  return (
                    <tr
                      key={route.id}
                      className={route.id === best ? "bg-soft" : ""}
                    >
                      <td className="border-b border-line p-3">
                        <button
                          type="button"
                          onClick={() => setChosen(route.id)}
                          className="font-semibold text-accent underline"
                        >
                          Route {i + 1}
                        </button>
                        <p className="mt-1 text-xs text-secondary">
                          {route.label}
                        </p>
                      </td>
                      <td className="border-b border-line p-3">
                        {(route.distance_m / 1000).toFixed(1)} km
                        <p>{routeHours(route.metrics.duration)}</p>
                        <p className="mt-1 text-xs text-secondary">
                          {route.estimated_arrival_at
                            ? displayTime(route.estimated_arrival_at)
                            : "Arrival uncertain"}
                        </p>
                      </td>
                      <td className="border-b border-line p-3">
                        {route.toll_road_metres === null
                          ? "Unknown"
                          : `${(route.toll_road_metres / 1000).toFixed(1)} km`}
                      </td>
                      <td className="border-b border-line p-3 text-xs">
                        <p>
                          Road/weather index:{" "}
                          {route.metrics.road_weather_exposure ?? "Unknown"}
                        </p>
                        <p className="mt-1">
                          Observed corridor excess:{" "}
                          {routeHours(route.metrics.state_transit_history)}
                        </p>
                        <p className="mt-1 text-secondary">
                          {route.history.sample_count} matching journeys
                        </p>
                      </td>
                      <td className="border-b border-line p-3">
                        <strong>
                          {route.feasibility === "EXCLUDED"
                            ? "Excluded"
                            : rank
                              ? `Rank ${rank.rank}`
                              : "Not comparable"}
                        </strong>
                        <p className="mt-1 text-xs">
                          {route.id === best
                            ? "Conditionally preferred"
                            : rank?.pareto_member
                              ? "Trade-off / Pareto option"
                              : ""}
                        </p>
                      </td>
                      <td className="border-b border-line p-3 text-xs">
                        {route.id === best
                          ? "Lowest weighted loss on the observed comparison factors."
                          : route.feasibility === "EXCLUDED"
                            ? route.reason_codes.map(routeWords).join(", ")
                            : best && route.comparison_to_best
                              ? `${(route.comparison_to_best.distance_delta_m / 1000).toFixed(1)} km versus preferred; ${routeHours(route.comparison_to_best.duration_delta_seconds)} travel difference.`
                              : "No current preferred route for comparison."}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <section className="rounded-lg border border-line p-4">
            <h4 className="font-semibold text-ink">
              Why this route has this position
            </h4>
            <p className="mt-1 text-sm text-secondary">
              Lower loss ranks better; this is not a confidence or safety
              percentage.
            </p>
            <ul className="mt-4 space-y-3">
              {ranking?.contributions.map((part) => (
                <li key={part.factor} className="text-sm">
                  <div className="flex flex-wrap justify-between gap-2">
                    <strong>{routeFactors[part.factor]}</strong>
                    <span>
                      {part.effective_weight_percent}% effective weight · loss{" "}
                      {part.weighted_loss.toFixed(3)}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 rounded bg-soft">
                    <div
                      className="h-full rounded bg-accent"
                      style={{
                        width: `${Math.max(0, Math.min(100, part.weighted_loss * 100))}%`,
                      }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-secondary">
                    Metric input:{" "}
                    {part.factor === "distance" ||
                    part.factor === "toll_exposure"
                      ? `${(part.value / 1000).toFixed(1)} km`
                      : part.factor === "duration" ||
                          part.factor === "state_transit_history"
                        ? routeHours(part.value)
                        : `${part.value} exposure index (not a risk probability)`}
                  </p>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-secondary">
              {active.road_names.length
                ? `Named roads: ${active.road_names.join(" · ")}`
                : "Road names were not supplied by the retained source."}
            </p>
            {active.fuel_estimate_minor && (
              <p className="mt-3 text-sm">
                Declared-input fuel estimate: ₹
                {(Number(active.fuel_estimate_minor) / 100).toFixed(2)}.
                Excludes tolls, carrier margin, taxes and other operating
                charges.
              </p>
            )}
          </section>
          {!!active.reason_codes.length && (
            <details open className="rounded-lg border border-line p-4">
              <summary className="cursor-pointer font-semibold">
                Checks still affecting this route
              </summary>
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm capitalize">
                {active.reason_codes.map((code) => (
                  <li key={code}>{routeWords(code)}</li>
                ))}
              </ul>
            </details>
          )}
          <FreightRouteEvidence candidate={active} study={study} />
        </>
      )}
    </section>
  );
}
