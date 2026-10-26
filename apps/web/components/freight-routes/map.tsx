"use client";

import { useMemo } from "react";
import type { RouteCandidate } from "@/lib/freight-routes";

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
  const drawing = useMemo(() => {
    const points = routes.flatMap((r) => r.geometry.coordinates);
    if (!points.length) return null;
    const [minX, maxX, minY, maxY] = points.reduce(
      (bounds, p) => [
        Math.min(bounds[0], p[0]),
        Math.max(bounds[1], p[0]),
        Math.min(bounds[2], p[1]),
        Math.max(bounds[3], p[1]),
      ],
      [Infinity, -Infinity, Infinity, -Infinity],
    );
    const scale = Math.min(
      660 / Math.max(maxX - minX, 0.01),
      300 / Math.max(maxY - minY, 0.01),
    );
    const project = (p: number[]) => [
      360 + (p[0] - (minX + maxX) / 2) * scale,
      170 - (p[1] - (minY + maxY) / 2) * scale,
    ];
    const path = (points: number[][]) =>
      points
        .filter(
          (_, i) =>
            i === points.length - 1 ||
            i % Math.max(1, Math.ceil(points.length / 2500)) === 0,
        )
        .map((p, i) => `${i ? "L" : "M"}${project(p).join(",")}`)
        .join(" ");
    const outlines = (value: unknown): string => {
      if (!Array.isArray(value) || !value.length) return "";
      if (Array.isArray(value[0]) && typeof value[0][0] === "number")
        return path(value as number[][]) + " Z";
      return value.map(outlines).join(" ");
    };
    return { project, path, outlines };
  }, [routes]);
  if (!drawing)
    return <p>No road geometry is available for this comparison.</p>;
  const active = routes.find((r) => r.id === selected) ?? routes[0];
  const start = active.geometry.coordinates[0],
    end = active.geometry.coordinates.at(-1)!;
  return (
    <figure className="min-w-0 overflow-hidden rounded-xl border border-line bg-soft">
      <svg
        viewBox="0 0 720 340"
        role="img"
        aria-label="Compared freight road routes"
        className="block max-h-[420px] w-full"
      >
        <defs>
          <clipPath id="freight-route-viewport">
            <rect width="720" height="340" />
          </clipPath>
          <pattern
            id="freight-map-grid"
            width="30"
            height="30"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M30 0H0V30"
              fill="none"
              stroke="currentColor"
              strokeOpacity=".05"
            />
          </pattern>
        </defs>
        <rect width="720" height="340" fill="url(#freight-map-grid)" />
        <g clipPath="url(#freight-route-viewport)">
          {active.corridor.state_outlines.map((state, index) => (
            <path
              key={`${state.state_code}:${index}`}
              d={drawing.outlines(state.geometry.coordinates)}
              fill="#e5edef"
              fillOpacity=".45"
              fillRule="evenodd"
              stroke="#9cb5bb"
              strokeWidth="1"
              strokeDasharray="3 3"
            >
              <title>{state.name} · reference boundary</title>
            </path>
          ))}
        </g>
        {routes
          .filter((r) => r.id !== selected)
          .map((r) => (
            <path
              key={r.id}
              d={drawing.path(r.geometry.coordinates)}
              fill="none"
              stroke={r.feasibility === "EXCLUDED" ? "#b45309" : "#78909c"}
              strokeWidth="2.5"
              strokeDasharray="6 5"
              opacity=".65"
            />
          ))}
        <path
          d={drawing.path(active.geometry.coordinates)}
          fill="none"
          stroke={active.feasibility === "EXCLUDED" ? "#b45309" : "#087f83"}
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {[start, end].map((point, i) => (
          <g
            key={i}
            transform={`translate(${drawing.project(point).join(",")})`}
          >
            <circle
              r="7"
              fill={i ? "#173642" : "#087f83"}
              stroke="white"
              strokeWidth="3"
            />
            <text
              y={i ? 25 : -16}
              textAnchor="middle"
              fontSize="12"
              fontWeight="600"
              fill="#173642"
            >
              {i ? "Delivery" : "Pickup"}
            </text>
          </g>
        ))}
      </svg>
      <figcaption className="space-y-2 border-t border-line bg-surface p-3 text-xs text-secondary">
        <p>
          {active.geometry_kind === "TOPOLOGICAL_SCHEMATIC"
            ? "Retained topology schematic — lines are not verified road geometry."
            : "Truck-route geometry from the recorded provider response. Dashed lines are compared alternatives."}
        </p>
        <p>{active.provider.attribution}</p>
        <div className="flex flex-wrap gap-2">
          {routes.map((r, i) => (
            <button
              key={r.id}
              type="button"
              aria-pressed={r.id === selected}
              onClick={() => onSelect(r.id)}
              className={`rounded-md border px-3 py-1.5 font-medium ${r.id === selected ? "border-accent bg-soft text-ink" : "border-line"}`}
            >
              Route {i + 1}
              {r.id === best ? " · preferred" : ""}
              {r.feasibility === "EXCLUDED" ? " · excluded" : ""}
            </button>
          ))}
        </div>
      </figcaption>
    </figure>
  );
}
