"use client";

import { useEffect, useRef, useState } from "react";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import {
  routeFactors,
  routePresets,
  type RouteContext,
  type RouteTruck,
  type RouteWeights,
} from "@/lib/freight-routes";
import type { FreightContext } from "@/lib/freight";
import { displayTime } from "@/lib/trades";
import { FreightRouteResult } from "./result";

const emptyTruck: RouteTruck = {
  height_m: "",
  width_m: "",
  length_m: "",
  tare_kg: "",
  axle_load_kg: "",
};
const truckLabels: Record<keyof RouteTruck, string> = {
  height_m: "Height (m)",
  width_m: "Width (m)",
  length_m: "Length (m)",
  tare_kg: "Combined tare (kg)",
  axle_load_kg: "Actual maximum axle load (kg)",
  maximum_loaded_kg: "Authorized loaded maximum (kg, if known)",
};
function departureDefault() {
  const time = new Date(Date.now() + 3600000);
  return new Date(time.getTime() - time.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

export function FreightRouteStudio({
  context: freight,
}: {
  context: FreightContext;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<RouteContext>(
    `/consignments/${freight.consignment_id}/freight-route-intelligence`,
    org,
  );
  const mutation = useOperationalMutation(org, resource.reload);
  const [mode, setMode] = useState<"LIVE" | "RETAINED">("LIVE");
  const [dataset, setDataset] = useState(freight.datasets[0]?.id ?? "");
  const [departure, setDeparture] = useState(departureDefault);
  const [truck, setTruck] = useState<RouteTruck>(emptyTruck);
  const [assigned, setAssigned] = useState(false);
  const initialized = useRef(false);
  const [weather, setWeather] = useState(true);
  const [stops, setStops] = useState("0");
  const [preset, setPreset] = useState("Balanced");
  const [weights, setWeights] = useState<RouteWeights>(routePresets.Balanced);
  const [selected, setSelected] = useState("");
  const data = resource.data;
  useEffect(() => {
    if (data && !initialized.current) {
      if (data.truck) {
        setTruck(data.truck);
        setAssigned(true);
      }
      initialized.current = true;
    }
  }, [data]);
  if (resource.error)
    return <p role="alert">Current route-intelligence context unavailable.</p>;
  if (!data) return <p role="status">Loading route-intelligence inputs…</p>;
  const sum = Object.values(weights).reduce((total, value) => total + value, 0);
  const canPrepare = freight.capabilities.includes("tradetwin.plan.prepare");
  async function compare() {
    setSelected("");
    const result = await mutation.run<{ id: string }>(
      `/consignments/${freight.consignment_id}/freight-route-studies`,
      {
        source_mode: mode,
        departure_at: new Date(departure).toISOString(),
        truck: assigned
          ? null
          : { ...truck, maximum_loaded_kg: truck.maximum_loaded_kg || null },
        dataset_revision_id: mode === "RETAINED" ? dataset : null,
        weights,
        include_weather: weather,
        planned_stop_seconds: Math.round(Number(stops) * 60),
      },
    );
    if (result) setSelected(result.id);
  }
  return (
    <section
      aria-label="India freight route intelligence"
      className="space-y-5 rounded-xl border border-line bg-surface p-4 sm:p-6"
    >
      <header>
        <p className="text-xs font-semibold uppercase tracking-wider text-accent">
          Road freight · state-wise comparison
        </p>
        <h3 className="mt-1 text-xl font-semibold text-ink">
          Find the best supported route
        </h3>
        <p className="mt-2 max-w-3xl text-sm text-secondary">
          Compare actual road alternatives with truck dimensions, state transit
          evidence, reviewed restrictions, weather and your organization’s
          corridor history. See the trade-offs before requesting or committing
          freight.
        </p>
      </header>
      {canPrepare && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void compare();
          }}
          className="space-y-4"
        >
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <label className="text-sm font-medium">
              Route source
              <select
                aria-label="Route source"
                value={mode}
                onChange={(event) =>
                  setMode(event.target.value as "LIVE" | "RETAINED")
                }
                className="mt-1 block w-full rounded-md border border-line bg-surface p-2"
              >
                <option value="LIVE">Live HGV road routes</option>
                <option value="RETAINED">Published retained topology</option>
              </select>
            </label>
            <label className="text-sm font-medium">
              Planned departure
              <input
                type="datetime-local"
                required
                value={departure}
                onChange={(event) => setDeparture(event.target.value)}
                className="mt-1 block w-full rounded-md border border-line p-2"
              />
            </label>
            <label className="text-sm font-medium">
              Declared operational stops (minutes)
              <input
                type="number"
                min="0"
                max="10080"
                required
                value={stops}
                onChange={(event) => setStops(event.target.value)}
                className="mt-1 block w-full rounded-md border border-line p-2"
              />
            </label>
            {mode === "RETAINED" && (
              <label className="text-sm font-medium">
                Published dataset
                <select
                  aria-label="Retained route dataset"
                  required
                  value={dataset}
                  onChange={(event) => setDataset(event.target.value)}
                  className="mt-1 block w-full rounded-md border border-line p-2"
                >
                  <option value="">Select a dataset</option>
                  {freight.datasets.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.dataset_code} · {item.version}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="text-sm font-medium">
              Comparison priority
              <select
                aria-label="Route comparison priority"
                value={preset}
                onChange={(event) => {
                  setPreset(event.target.value);
                  if (routePresets[event.target.value])
                    setWeights(routePresets[event.target.value]);
                }}
                className="mt-1 block w-full rounded-md border border-line bg-surface p-2"
              >
                {[...Object.keys(routePresets), "Custom"].map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </select>
            </label>
          </div>
          {!data.pins_confirmed && (
            <p className="rounded-md border border-line bg-soft p-3 text-sm">
              Confirm the exact pickup and drop gates in the routing form below
              before comparing routes.
            </p>
          )}
          {mode === "LIVE" && !data.live_routing_configured && (
            <p className="rounded-md border border-line bg-soft p-3 text-sm">
              Live routing is not configured on the server. Configure the ORS
              integration or select an explicitly retained topology. Live
              failures never use a demo route.
            </p>
          )}
          <details className="rounded-lg border border-line p-3">
            <summary className="cursor-pointer text-sm font-semibold">
              Truck inputs · cargo {data.cargo_weight_kg} kg
            </summary>
            {data.truck && (
              <label className="mt-3 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={assigned}
                  onChange={(event) => setAssigned(event.target.checked)}
                />
                Use the assigned truck’s current routing profile and reviewed
                permit references
              </label>
            )}
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {(Object.keys(truckLabels) as (keyof RouteTruck)[]).map((key) => (
                <label key={key} className="text-sm">
                  {truckLabels[key]}
                  <input
                    aria-label={truckLabels[key]}
                    type="number"
                    step="any"
                    min="0.001"
                    required={!assigned && key !== "maximum_loaded_kg"}
                    disabled={assigned}
                    value={truck[key] ?? ""}
                    onChange={(event) =>
                      setTruck((previous) => ({
                        ...previous,
                        [key]: event.target.value,
                      }))
                    }
                    className="mt-1 block w-full rounded-md border border-line p-2 disabled:bg-soft"
                  />
                </label>
              ))}
            </div>
            {!assigned && (
              <p className="mt-3 text-xs text-secondary">
                Declared truck inputs guide the road provider. Vehicle-bound
                permits and release approvals are not transferred to a
                hypothetical truck.
              </p>
            )}
          </details>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {(Object.keys(routeFactors) as (keyof RouteWeights)[]).map(
              (factor) => (
                <label
                  key={factor}
                  className="rounded-lg border border-line bg-soft p-3 text-xs font-medium text-secondary"
                >
                  {routeFactors[factor]}
                  {preset === "Custom" ? (
                    <input
                      aria-label={`${routeFactors[factor]} weight percent`}
                      type="number"
                      min="0"
                      max="100"
                      required
                      value={weights[factor] / 100}
                      onChange={(event) =>
                        setWeights((previous) => ({
                          ...previous,
                          [factor]: Math.round(
                            Number(event.target.value) * 100,
                          ),
                        }))
                      }
                      className="mt-2 block w-full rounded border border-line bg-surface p-2 text-sm text-ink"
                    />
                  ) : (
                    <p className="mt-2 text-lg font-semibold text-ink">
                      {weights[factor] / 100}%
                    </p>
                  )}
                </label>
              ),
            )}
          </div>
          {sum !== 10000 && <p role="alert">Weights must total 100%.</p>}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={weather}
              onChange={(event) => setWeather(event.target.checked)}
            />
            Include sampled forecasts for estimated route traversal times
          </label>
          <button
            type="submit"
            disabled={
              mutation.pending ||
              sum !== 10000 ||
              !data.pins_confirmed ||
              (mode === "LIVE" && !data.live_routing_configured)
            }
            className="rounded-md bg-accent px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {mutation.pending
              ? "Requesting comparison…"
              : "Compare freight routes"}
          </button>
        </form>
      )}
      {mutation.error && (
        <p role="alert" className="rounded-md border border-line p-3 text-sm">
          {mutation.error.message}
        </p>
      )}
      {!!data.studies.length && (
        <label className="block text-sm font-medium">
          Saved route comparisons
          <select
            aria-label="Saved route comparisons"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            className="mt-1 block w-full rounded-md border border-line bg-surface p-2"
          >
            <option value="">Select a comparison</option>
            {data.studies.map((study) => (
              <option key={study.id} value={study.id}>
                {displayTime(study.created_at)} · {study.source_mode} ·{" "}
                {study.job_state}
              </option>
            ))}
          </select>
        </label>
      )}
      {selected && !mutation.error && (
        <FreightRouteResult key={org + selected} id={selected} />
      )}
    </section>
  );
}
