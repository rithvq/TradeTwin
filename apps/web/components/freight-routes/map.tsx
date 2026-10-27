"use client";

import { useMemo } from "react";
import type { RouteCandidate } from "@/lib/freight-routes";
import { geographicRoutes, routeColor } from "@/lib/freight-map";
import { FreightMapCanvas } from "./map-canvas";

export function FreightRouteMap({
  routes,
  selected,
  best,
  onSelect,
}: {
  routes: RouteCandidate[];
  selected: string;
  best: string | null;
  onSelect: (id: string) => void;
}) {
  const mapped = useMemo(() => geographicRoutes(routes), [routes]);
  const active = mapped.find((r) => r.id === selected) ?? mapped[0];
  if (!active)
    return (
      <p>No geographic route coordinates are available for this comparison.</p>
    );
  return (
    <figure
      aria-label="India freight route map"
      role="region"
      className="min-w-0 overflow-hidden rounded-xl border border-line bg-surface"
    >
      <FreightMapCanvas
        routes={mapped}
        selected={active.id}
        onSelect={onSelect}
      />
      <figcaption className="space-y-3 border-t border-line p-3 text-xs text-secondary">
        <div
          className="flex flex-wrap gap-2"
          aria-label="Map route alternatives"
        >
          {mapped.map((route, index) => (
            <button
              key={route.id}
              type="button"
              aria-pressed={route.id === active.id}
              onClick={() => onSelect(route.id)}
              className={`inline-flex items-center gap-2 rounded-md border px-3 py-2 font-semibold ${route.id === active.id ? "border-accent bg-soft text-ink" : "border-line"}`}
            >
              <span
                className="h-0.5 w-5"
                style={{ backgroundColor: routeColor(route, active.id) }}
                aria-hidden="true"
              />
              Route {index + 1}
              {route.id === best ? " · preferred" : ""}
              {route.feasibility === "EXCLUDED" ? " · excluded" : ""}
            </button>
          ))}
        </div>
        <p>
          {active.geometry_kind !== "ROAD_GEOMETRY"
            ? "Retained topology schematic on the map — dashed connections are simulated, not measured highways. Use Live truck roads in the route optimizer for road-following routes."
            : "Routes follow the provider’s recorded road geometry. Select an alternative to inspect it."}
        </p>
        <div className="flex flex-wrap justify-between gap-x-4 gap-y-1">
          <span>{active.provider.attribution}</span>
          <a
            href="https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            State reference: DataMeet / geoBoundaries · 2011 · CC BY 2.5 IN
          </a>
        </div>
      </figcaption>
    </figure>
  );
}
