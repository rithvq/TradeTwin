"use client";

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { apiFetch, type Shipment } from "../lib/shipments";

type ConsignmentDraft = {
  clientId: string;
  product_name: string;
  product_description: string;
  quantity: string;
  declared_value: string;
  currency: string;
  country_of_origin: string;
  destination_country: string;
  proposed_hs_code: string;
};

type RouteLegDraft = {
  clientId: string;
  origin_country: string;
  destination_country: string;
  transport_mode: string;
  carrier_name: string;
};

type ShipmentDraft = {
  shipment_reference: string;
  exporter_country: string;
  importer_country: string;
  transport_mode: string;
  planned_departure_at: string;
  planned_arrival_at: string;
  consignments: ConsignmentDraft[];
  route_legs: RouteLegDraft[];
};

const inputClassName =
  "mt-2 w-full rounded border border-slate-300 bg-white px-3 py-2 text-slate-950 outline-none placeholder:text-slate-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-100";

const countryOptions = [
  "India",
  "UAE",
  "Germany",
  "Singapore",
  "Netherlands",
  "United Kingdom",
  "United States",
];

const transportModes = ["SEA", "AIR", "ROAD", "RAIL", "MULTIMODAL"];

function toDateTimeLocal(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

function createReference(): string {
  return `TT-${Date.now().toString().slice(-6)}`;
}

function createClientId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptyConsignment(
  clientId = "consignment-initial",
  originCountry = "",
  destinationCountry = "",
): ConsignmentDraft {
  return {
    clientId,
    product_name: "",
    product_description: "",
    quantity: "1",
    declared_value: "0.00",
    currency: "USD",
    country_of_origin: originCountry,
    destination_country: destinationCountry,
    proposed_hs_code: "",
  };
}

function emptyRouteLeg(
  clientId = "route-leg-initial",
  originCountry = "",
  destinationCountry = "",
  transportMode = "SEA",
): RouteLegDraft {
  return {
    clientId,
    origin_country: originCountry,
    destination_country: destinationCountry,
    transport_mode: transportMode,
    carrier_name: "",
  };
}

function createBlankDraft(): ShipmentDraft {
  return {
    shipment_reference: "",
    exporter_country: "",
    importer_country: "",
    transport_mode: "SEA",
    planned_departure_at: "",
    planned_arrival_at: "",
    consignments: [emptyConsignment()],
    route_legs: [emptyRouteLeg()],
  };
}

function createDemoDraft(): ShipmentDraft {
  const now = new Date();
  const departure = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const arrival = new Date(now.getTime() + 22 * 24 * 60 * 60 * 1000);

  return {
    shipment_reference: createReference(),
    exporter_country: "India",
    importer_country: "Germany",
    transport_mode: "SEA",
    planned_departure_at: toDateTimeLocal(departure),
    planned_arrival_at: toDateTimeLocal(arrival),
    consignments: [
      {
        clientId: "demo-consignment-a",
        product_name: "Lithium batteries",
        product_description: "Rechargeable lithium battery packs for industrial equipment.",
        quantity: "120",
        declared_value: "18000.00",
        currency: "USD",
        country_of_origin: "India",
        destination_country: "Germany",
        proposed_hs_code: "",
      },
      {
        clientId: "demo-consignment-b",
        product_name: "Consumer electronics",
        product_description: "Packaged consumer electronic devices for retail distribution.",
        quantity: "240",
        declared_value: "32000.00",
        currency: "USD",
        country_of_origin: "India",
        destination_country: "UAE",
        proposed_hs_code: "",
      },
    ],
    route_legs: [
      {
        clientId: "demo-route-leg-1",
        origin_country: "India",
        destination_country: "UAE",
        transport_mode: "SEA",
        carrier_name: "TradeTwin Demo Line",
      },
      {
        clientId: "demo-route-leg-2",
        origin_country: "UAE",
        destination_country: "Germany",
        transport_mode: "SEA",
        carrier_name: "TradeTwin Demo Line",
      },
    ],
  };
}

export function ShipmentForm() {
  const [draft, setDraft] = useState<ShipmentDraft>(createBlankDraft);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setDraft((current) => {
      if (
        current.shipment_reference ||
        current.planned_departure_at ||
        current.planned_arrival_at
      ) {
        return current;
      }

      const now = new Date();
      return {
        ...current,
        shipment_reference: createReference(),
        planned_departure_at: toDateTimeLocal(
          new Date(now.getTime() + 24 * 60 * 60 * 1000),
        ),
        planned_arrival_at: toDateTimeLocal(
          new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000),
        ),
      };
    });
  }, []);

  function updateField(
    field: Exclude<keyof ShipmentDraft, "consignments" | "route_legs">,
    value: string,
  ) {
    setNotice(null);
    setDraft((current) => ({ ...current, [field]: value }));
  }

  function updateExporterCountry(value: string) {
    setNotice(null);
    setDraft((current) => {
      const previous = current.exporter_country;
      return {
        ...current,
        exporter_country: value,
        consignments: current.consignments.map((item) => ({
          ...item,
          country_of_origin:
            !item.country_of_origin || item.country_of_origin === previous
              ? value
              : item.country_of_origin,
        })),
        route_legs: current.route_legs.map((leg, index) =>
          index === 0 && (!leg.origin_country || leg.origin_country === previous)
            ? { ...leg, origin_country: value }
            : leg,
        ),
      };
    });
  }

  function updateImporterCountry(value: string) {
    setNotice(null);
    setDraft((current) => {
      const previous = current.importer_country;
      const lastLegIndex = current.route_legs.length - 1;
      return {
        ...current,
        importer_country: value,
        consignments: current.consignments.map((item) => ({
          ...item,
          destination_country:
            !item.destination_country || item.destination_country === previous
              ? value
              : item.destination_country,
        })),
        route_legs: current.route_legs.map((leg, index) =>
          index === lastLegIndex &&
          (!leg.destination_country || leg.destination_country === previous)
            ? { ...leg, destination_country: value }
            : leg,
        ),
      };
    });
  }

  function updateTransportMode(value: string) {
    setNotice(null);
    setDraft((current) => {
      const previous = current.transport_mode;
      return {
        ...current,
        transport_mode: value,
        route_legs: current.route_legs.map((leg) => ({
          ...leg,
          transport_mode:
            !leg.transport_mode || leg.transport_mode === previous
              ? value
              : leg.transport_mode,
        })),
      };
    });
  }

  function updateConsignment(index: number, field: keyof ConsignmentDraft, value: string) {
    setNotice(null);
    setDraft((current) => ({
      ...current,
      consignments: current.consignments.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: value } : item,
      ),
    }));
  }

  function addConsignment() {
    setNotice(null);
    setDraft((current) => ({
      ...current,
      consignments: [
        ...current.consignments,
        emptyConsignment(
          createClientId("consignment"),
          current.exporter_country,
          current.importer_country,
        ),
      ],
    }));
  }

  function removeConsignment(index: number) {
    setNotice(null);
    setDraft((current) => ({
      ...current,
      consignments: current.consignments.filter((_, itemIndex) => itemIndex !== index),
    }));
  }

  function updateRouteLeg(index: number, field: keyof RouteLegDraft, value: string) {
    setNotice(null);
    setDraft((current) => {
      const previousDestination = current.route_legs[index]?.destination_country;
      return {
        ...current,
        route_legs: current.route_legs.map((leg, legIndex) => {
          if (legIndex === index) {
            return { ...leg, [field]: value };
          }
          if (
            field === "destination_country" &&
            legIndex === index + 1 &&
            (!leg.origin_country || leg.origin_country === previousDestination)
          ) {
            return { ...leg, origin_country: value };
          }
          return leg;
        }),
      };
    });
  }

  function addRouteLeg() {
    setNotice(null);
    setDraft((current) => {
      const lastLeg = current.route_legs.at(-1);
      return {
        ...current,
        route_legs: [
          ...current.route_legs,
          emptyRouteLeg(
            createClientId("route-leg"),
            lastLeg?.destination_country || current.exporter_country,
            current.importer_country,
            current.transport_mode,
          ),
        ],
      };
    });
  }

  function removeRouteLeg(index: number) {
    setNotice(null);
    setDraft((current) => ({
      ...current,
      route_legs: current.route_legs.filter((_, legIndex) => legIndex !== index),
    }));
  }

  function loadDemoScenario() {
    setError(null);
    setNotice("Demo scenario loaded.");
    setDraft(createDemoDraft());
  }

  async function submitShipment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);

    const departure = new Date(draft.planned_departure_at);
    const arrival = new Date(draft.planned_arrival_at);
    if (Number.isNaN(departure.getTime()) || Number.isNaN(arrival.getTime())) {
      setError("Enter valid planned departure and arrival dates.");
      return;
    }
    if (arrival <= departure) {
      setError("Planned arrival must be later than planned departure.");
      return;
    }
    if (draft.consignments.length === 0) {
      setError("Add at least one consignment.");
      return;
    }
    if (draft.route_legs.length === 0) {
      setError("Add at least one route leg.");
      return;
    }

    setSubmitting(true);
    try {
      const shipment = await apiFetch<Shipment>("/shipments", {
        method: "POST",
        body: JSON.stringify({
          shipment_reference: draft.shipment_reference.trim(),
          exporter_country: draft.exporter_country.trim(),
          importer_country: draft.importer_country.trim(),
          transport_mode: draft.transport_mode,
          planned_departure_at: departure.toISOString(),
          planned_arrival_at: arrival.toISOString(),
          consignments: draft.consignments.map((item) => ({
            product_name: item.product_name.trim(),
            product_description: item.product_description.trim(),
            quantity: Number(item.quantity),
            declared_value: item.declared_value,
            currency: item.currency.trim().toUpperCase(),
            country_of_origin: item.country_of_origin.trim(),
            destination_country: item.destination_country.trim(),
            proposed_hs_code: item.proposed_hs_code.trim() || null,
          })),
          route_legs: draft.route_legs.map((leg, index) => ({
            sequence_number: index + 1,
            origin_country: leg.origin_country.trim(),
            destination_country: leg.destination_country.trim(),
            transport_mode: leg.transport_mode,
            carrier_name: leg.carrier_name.trim(),
          })),
        }),
      });
      window.location.assign(`/shipments/${shipment.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create shipment");
      setSubmitting(false);
    }
  }

  return (
    <section className="rounded border border-slate-200 bg-white p-5 sm:p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-xl font-semibold text-slate-950">Create Shipment</h2>
        <button
          type="button"
          onClick={loadDemoScenario}
          className="rounded border border-teal-700 px-3 py-2 text-sm font-semibold text-teal-800 hover:bg-teal-50"
        >
          Load demo scenario
        </button>
      </div>

      {notice ? (
        <p className="mt-4 rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      ) : null}

      <form onSubmit={submitShipment} className="mt-5 space-y-7">
        <fieldset>
          <legend className="text-base font-semibold text-slate-950">Shipment details</legend>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="text-sm font-medium text-slate-700">Shipment reference</span>
              <input
                required
                value={draft.shipment_reference}
                onChange={(event) => updateField("shipment_reference", event.target.value)}
                className={inputClassName}
                placeholder="TT-100001"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Exporter country</span>
              <input
                required
                list="tradetwin-country-options"
                value={draft.exporter_country}
                onChange={(event) => updateExporterCountry(event.target.value)}
                className={inputClassName}
                placeholder="India"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Importer country</span>
              <input
                required
                list="tradetwin-country-options"
                value={draft.importer_country}
                onChange={(event) => updateImporterCountry(event.target.value)}
                className={inputClassName}
                placeholder="Germany"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Primary transport mode</span>
              <select
                value={draft.transport_mode}
                onChange={(event) => updateTransportMode(event.target.value)}
                className={inputClassName}
              >
                {transportModes.map((mode) => (
                  <option key={mode} value={mode}>
                    {mode}
                  </option>
                ))}
              </select>
            </label>
            <div aria-hidden="true" className="hidden sm:block" />
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Planned departure</span>
              <input
                required
                type="datetime-local"
                value={draft.planned_departure_at}
                onChange={(event) => updateField("planned_departure_at", event.target.value)}
                className={inputClassName}
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Planned arrival</span>
              <input
                required
                type="datetime-local"
                value={draft.planned_arrival_at}
                onChange={(event) => updateField("planned_arrival_at", event.target.value)}
                className={inputClassName}
              />
            </label>
          </div>
        </fieldset>

        <section className="border-t border-slate-200 pt-6">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-base font-semibold text-slate-950">
              Route legs ({draft.route_legs.length})
            </h3>
            <button
              type="button"
              onClick={addRouteLeg}
              className="rounded border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Add route leg
            </button>
          </div>

          <div className="mt-4 space-y-4">
            {draft.route_legs.map((leg, index) => (
              <div key={leg.clientId} className="rounded border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-semibold text-slate-900">Leg {index + 1}</h3>
                  {draft.route_legs.length > 1 ? (
                    <button
                      type="button"
                      onClick={() => removeRouteLeg(index)}
                      className="text-sm font-medium text-red-700 hover:text-red-900"
                    >
                      Remove
                    </button>
                  ) : null}
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Origin</span>
                    <input
                      required
                      list="tradetwin-country-options"
                      value={leg.origin_country}
                      onChange={(event) =>
                        updateRouteLeg(index, "origin_country", event.target.value)
                      }
                      className={inputClassName}
                      placeholder="Origin country"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Destination</span>
                    <input
                      required
                      list="tradetwin-country-options"
                      value={leg.destination_country}
                      onChange={(event) =>
                        updateRouteLeg(index, "destination_country", event.target.value)
                      }
                      className={inputClassName}
                      placeholder="Destination country"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Transport mode</span>
                    <select
                      value={leg.transport_mode}
                      onChange={(event) =>
                        updateRouteLeg(index, "transport_mode", event.target.value)
                      }
                      className={inputClassName}
                    >
                      {transportModes.map((mode) => (
                        <option key={mode} value={mode}>
                          {mode}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Carrier name</span>
                    <input
                      required
                      value={leg.carrier_name}
                      onChange={(event) =>
                        updateRouteLeg(index, "carrier_name", event.target.value)
                      }
                      className={inputClassName}
                      placeholder="Carrier"
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="border-t border-slate-200 pt-6">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-base font-semibold text-slate-950">
              Consignments ({draft.consignments.length})
            </h3>
            <button
              type="button"
              onClick={addConsignment}
              className="rounded border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Add consignment
            </button>
          </div>

          <div className="mt-4 space-y-4">
            {draft.consignments.map((item, index) => (
              <div key={item.clientId} className="rounded border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-semibold text-slate-900">Consignment {index + 1}</h3>
                  {draft.consignments.length > 1 ? (
                    <button
                      type="button"
                      onClick={() => removeConsignment(index)}
                      className="text-sm font-medium text-red-700 hover:text-red-900"
                    >
                      Remove
                    </button>
                  ) : null}
                </div>

                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Product name</span>
                    <input
                      required
                      value={item.product_name}
                      onChange={(event) =>
                        updateConsignment(index, "product_name", event.target.value)
                      }
                      className={inputClassName}
                      placeholder="Product"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Proposed HS code</span>
                    <input
                      value={item.proposed_hs_code}
                      onChange={(event) =>
                        updateConsignment(index, "proposed_hs_code", event.target.value)
                      }
                      className={inputClassName}
                      placeholder="Optional"
                    />
                  </label>
                  <label className="block sm:col-span-2">
                    <span className="text-sm font-medium text-slate-700">
                      Product description
                    </span>
                    <textarea
                      required
                      rows={2}
                      value={item.product_description}
                      onChange={(event) =>
                        updateConsignment(index, "product_description", event.target.value)
                      }
                      className={inputClassName}
                      placeholder="Description"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Quantity</span>
                    <input
                      required
                      type="number"
                      min="1"
                      step="1"
                      value={item.quantity}
                      onChange={(event) =>
                        updateConsignment(index, "quantity", event.target.value)
                      }
                      className={inputClassName}
                    />
                  </label>
                  <div className="grid grid-cols-[minmax(0,1fr)_100px] gap-3">
                    <label className="block">
                      <span className="text-sm font-medium text-slate-700">Declared value</span>
                      <input
                        required
                        type="number"
                        min="0"
                        step="0.01"
                        value={item.declared_value}
                        onChange={(event) =>
                          updateConsignment(index, "declared_value", event.target.value)
                        }
                        className={inputClassName}
                      />
                    </label>
                    <label className="block">
                      <span className="text-sm font-medium text-slate-700">Currency</span>
                      <input
                        required
                        list="tradetwin-currency-options"
                        maxLength={3}
                        value={item.currency}
                        onChange={(event) =>
                          updateConsignment(index, "currency", event.target.value)
                        }
                        className={inputClassName}
                      />
                    </label>
                  </div>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">Country of origin</span>
                    <input
                      required
                      list="tradetwin-country-options"
                      value={item.country_of_origin}
                      onChange={(event) =>
                        updateConsignment(index, "country_of_origin", event.target.value)
                      }
                      className={inputClassName}
                      placeholder="Origin country"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">
                      Destination country
                    </span>
                    <input
                      required
                      list="tradetwin-country-options"
                      value={item.destination_country}
                      onChange={(event) =>
                        updateConsignment(index, "destination_country", event.target.value)
                      }
                      className={inputClassName}
                      placeholder="Destination country"
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </section>

        <datalist id="tradetwin-country-options">
          {countryOptions.map((country) => (
            <option key={country} value={country} />
          ))}
        </datalist>
        <datalist id="tradetwin-currency-options">
          {["USD", "EUR", "INR", "AED", "GBP"].map((currency) => (
            <option key={currency} value={currency} />
          ))}
        </datalist>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-teal-700 px-4 py-3 font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {submitting ? "Creating shipment..." : "Create shipment"}
        </button>
      </form>
    </section>
  );
}
