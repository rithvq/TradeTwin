"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch, displayStatus, type Shipment } from "../lib/shipments";

const now = new Date();
const plannedDeparture = new Date(now.getTime() + 24 * 60 * 60 * 1000);
const plannedArrival = new Date(now.getTime() + 22 * 24 * 60 * 60 * 1000);

export default function ShipmentHome() {
  const [shipments, setShipments] = useState<Shipment[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reference = useMemo(() => `TT-${Date.now().toString().slice(-6)}`, []);

  const loadShipments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setShipments(await apiFetch<Shipment[]>("/shipments"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load shipments");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadShipments();
  }, [loadShipments]);

  async function createDemoShipment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    setSubmitting(true);
    setError(null);
    const shipmentReference = String(formData.get("shipment_reference") || reference);
    try {
      const shipment = await apiFetch<Shipment>("/shipments", {
        method: "POST",
        body: JSON.stringify({
          shipment_reference: shipmentReference,
          exporter_country: "India",
          importer_country: "Germany",
          transport_mode: "SEA",
          planned_departure_at: plannedDeparture.toISOString(),
          planned_arrival_at: plannedArrival.toISOString(),
          consignments: [
            {
              product_name: "Lithium batteries",
              product_description: "Rechargeable lithium battery packs for industrial equipment.",
              quantity: 120,
              declared_value: "18000.00",
              currency: "USD",
              country_of_origin: "India",
              destination_country: "Germany",
            },
            {
              product_name: "Consumer electronics",
              product_description: "Packaged consumer electronic devices for retail distribution.",
              quantity: 240,
              declared_value: "32000.00",
              currency: "USD",
              country_of_origin: "India",
              destination_country: "UAE",
            },
          ],
          route_legs: [
            {
              sequence_number: 1,
              origin_country: "India",
              destination_country: "UAE",
              transport_mode: "SEA",
              carrier_name: "TradeTwin Demo Line",
            },
            {
              sequence_number: 2,
              origin_country: "UAE",
              destination_country: "Germany",
              transport_mode: "SEA",
              carrier_name: "TradeTwin Demo Line",
            },
          ],
        }),
      });
      window.location.href = `/shipments/${shipment.id}`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create shipment");
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f6f8fb]">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <div>
            <p className="text-sm font-semibold text-teal-700">TradeTwin</p>
            <h1 className="mt-1 text-2xl font-semibold text-slate-950">
              TradeTwin Operations Console
            </h1>
          </div>
          <span className="rounded bg-emerald-100 px-3 py-1 text-sm font-medium text-emerald-800">
            Phase 7
          </span>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[420px_1fr]">
        <section className="rounded border border-slate-200 bg-white p-5">
          <h2 className="text-lg font-semibold text-slate-950">Create Shipment</h2>
          <form onSubmit={createDemoShipment} className="mt-5 space-y-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Shipment reference</span>
              <input
                name="shipment_reference"
                defaultValue={reference}
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-slate-950 outline-none focus:border-teal-600"
              />
            </label>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded border border-slate-200 bg-slate-50 p-3">
                <span className="font-medium text-slate-950">Consignment A</span>
                <p className="mt-1 text-slate-600">Lithium batteries to Germany</p>
              </div>
              <div className="rounded border border-slate-200 bg-slate-50 p-3">
                <span className="font-medium text-slate-950">Consignment B</span>
                <p className="mt-1 text-slate-600">Consumer electronics to UAE</p>
              </div>
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded bg-teal-700 px-4 py-2.5 font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {submitting ? "Creating..." : "Create India to UAE to Germany shipment"}
            </button>
          </form>
        </section>

        <section className="rounded border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-lg font-semibold text-slate-950">Shipment List</h2>
            <button
              type="button"
              onClick={() => void loadShipments()}
              className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Refresh
            </button>
          </div>

          {error ? <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
          {loading ? <p className="mt-4 text-sm text-slate-600">Loading shipments...</p> : null}

          <div className="mt-5 divide-y divide-slate-200">
            {shipments.map((shipment) => (
              <Link
                key={shipment.id}
                href={`/shipments/${shipment.id}`}
                className="grid gap-3 py-4 hover:bg-slate-50 sm:grid-cols-[1fr_160px]"
              >
                <div>
                  <p className="font-semibold text-slate-950">{shipment.shipment_reference}</p>
                  <p className="mt-1 text-sm text-slate-600">
                    {shipment.exporter_country} to {shipment.importer_country} via{" "}
                    {shipment.transport_mode}
                  </p>
                </div>
                <div className="text-left sm:text-right">
                  <span className="rounded bg-amber-100 px-2.5 py-1 text-sm font-medium text-amber-900">
                    {displayStatus(shipment.status)}
                  </span>
                  <p className="mt-2 text-sm text-slate-500">
                    {shipment.consignments.length} consignments
                  </p>
                </div>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
