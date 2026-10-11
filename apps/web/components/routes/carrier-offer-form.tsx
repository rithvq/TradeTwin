"use client";

import { Plus, Trash2, Save } from "lucide-react";
import type { RouteMemoryState } from "@/hooks/use-route-memory";

type Props = Pick<
  RouteMemoryState,
  | "busy"
  | "form"
  | "setForm"
  | "vehicle"
  | "setVehicle"
  | "places"
  | "setPlaces"
  | "placeValue"
  | "run"
  | "request"
  | "setMessage"
>;

const button =
  "inline-flex items-center justify-center gap-2 rounded border px-3 py-2 text-sm font-medium disabled:opacity-50";
const input = "mt-1 block w-full min-w-0 rounded border bg-white p-2 text-sm";

export function CarrierOfferForm({
  busy,
  form,
  setForm,
  vehicle,
  setVehicle,
  places,
  setPlaces,
  placeValue,
  run,
  request,
  setMessage,
}: Props) {
  return (
    <details>
      <summary className="cursor-pointer font-semibold">
        Add reviewed carrier offer
      </summary>
      <form
        className="mt-4 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const numericVehicle = Object.fromEntries(
              Object.entries(vehicle).map(([k, v]) => [
                k,
                k === "hazmat" ? v : Number(v),
              ]),
            );
            await request("/offers", {
              ...form,
              total_price_inr: Number(form.total_price_inr),
              duration_hours: Number(form.duration_hours),
              observed_at: new Date(form.observed_at).toISOString(),
              valid_until: new Date(form.valid_until).toISOString(),
              places,
              vehicle: numericVehicle,
              all_inclusive: true,
            });
            setMessage(
              "Versioned offer saved. Earlier offers remain in history.",
            );
          });
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {(
            [
              ["carrier", "Carrier", "text"],
              ["reference", "Quote reference", "text"],
              ["total_price_inr", "All-inclusive price (INR)", "number"],
              ["duration_hours", "Carrier duration (hours)", "number"],
              ["observed_at", "Quote observed at", "datetime-local"],
              [
                "valid_until",
                "Valid until departure / booking",
                "datetime-local",
              ],
              ["source_url", "Quote source URL", "url"],
              ["source_reference", "Source document reference", "text"],
            ] as const
          ).map(([key, label, type]) => (
            <label key={key} className="text-sm font-medium">
              {label}
              <input
                className={input}
                required
                type={type}
                min={type === "number" ? "0.01" : undefined}
                step="any"
                value={form[key]}
                onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              />
            </label>
          ))}
        </div>
        <fieldset className="space-y-3">
          <legend className="font-medium">Route stops</legend>
          {places.map((place, i) => (
            <div
              key={i}
              className="grid grid-cols-2 items-end gap-3 border-b pb-3 md:grid-cols-6"
            >
              {(
                [
                  ["state", "State"],
                  ["city", "City"],
                  ["pincode", "PIN code"],
                  ["longitude", "Longitude"],
                  ["latitude", "Latitude"],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="min-w-0 text-sm">
                  {label}
                  <input
                    aria-label={`Stop ${i + 1} ${label}`}
                    className={input}
                    required={!["longitude", "latitude"].includes(key)}
                    value={place[key] ?? ""}
                    type={
                      ["longitude", "latitude"].includes(key)
                        ? "number"
                        : "text"
                    }
                    step="any"
                    onChange={(e) => placeValue(i, key, e.target.value)}
                  />
                </label>
              ))}
              <button
                type="button"
                className={button}
                title="Remove stop"
                aria-label={`Remove stop ${i + 1}`}
                disabled={places.length <= 2}
                onClick={() => setPlaces(places.filter((_, j) => j !== i))}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          <button
            type="button"
            className={button}
            onClick={() =>
              setPlaces([
                ...places.slice(0, -1),
                { state: "", city: "", pincode: "" },
                places[places.length - 1],
              ])
            }
          >
            <Plus size={16} />
            Add intermediate stop
          </button>
        </fieldset>
        <fieldset>
          <legend className="mb-3 font-medium">Quoted vehicle</legend>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {(
              [
                ["weight", "Gross weight (tonnes)"],
                ["height", "Height (m)"],
                ["width", "Width (m)"],
                ["length", "Length (m)"],
                ["axleload", "Axle load (tonnes)"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="text-sm">
                {label}
                <input
                  className={input}
                  required
                  type="number"
                  min="0.01"
                  step="any"
                  value={vehicle[key]}
                  onChange={(e) =>
                    setVehicle({ ...vehicle, [key]: e.target.value })
                  }
                />
              </label>
            ))}
          </div>
          <label className="mt-3 flex gap-2 text-sm">
            <input
              type="checkbox"
              checked={vehicle.hazmat}
              onChange={(e) =>
                setVehicle({ ...vehicle, hazmat: e.target.checked })
              }
            />
            Hazardous goods
          </label>
        </fieldset>
        <label className="block text-sm font-medium">
          Review rationale
          <textarea
            className={input}
            minLength={20}
            required
            value={form.review_note}
            onChange={(e) => setForm({ ...form, review_note: e.target.value })}
          />
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            className="mt-1"
            type="checkbox"
            checked={form.coverage_confirmed}
            onChange={(e) =>
              setForm({ ...form, coverage_confirmed: e.target.checked })
            }
          />
          Carrier capacity, route restrictions and all charges (fuel, tolls, tax
          and handling) have been reviewed for this shipment.
        </label>
        <button className={button} disabled={busy}>
          <Save size={16} />
          Save offer version
        </button>
      </form>
    </details>
  );
}
