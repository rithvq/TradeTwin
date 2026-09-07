"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ShipmentForm } from "../components/shipment-form";
import { apiFetch, deleteShipment, displayStatus, type Shipment } from "../lib/shipments";

export default function ShipmentHome() {
  const [shipments, setShipments] = useState<Shipment[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingShipmentId, setDeletingShipmentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  async function handleDeleteShipment(shipment: Shipment) {
    const confirmed = window.confirm(
      `Delete shipment ${shipment.shipment_reference}? ` +
        "This removes its consignments, route legs, events, and graph projection.",
    );
    if (!confirmed) {
      return;
    }

    setDeletingShipmentId(shipment.id);
    setError(null);
    try {
      await deleteShipment(shipment.id);
      setShipments((current) => current.filter((item) => item.id !== shipment.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete shipment");
    } finally {
      setDeletingShipmentId(null);
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

      <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 xl:grid-cols-[minmax(0,3fr)_minmax(420px,2fr)]">
        <ShipmentForm />

        <section className="self-start rounded border border-slate-200 bg-white p-5">
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
              <div key={shipment.id} className="py-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <Link
                    href={`/shipments/${shipment.id}`}
                    className="min-w-0 flex-1 rounded px-2 py-1 hover:bg-slate-50"
                  >
                    <p className="font-semibold text-slate-950">
                      {shipment.shipment_reference}
                    </p>
                    <p className="mt-1 text-sm text-slate-600">
                      {shipment.exporter_country} to {shipment.importer_country} via{" "}
                      {shipment.transport_mode}
                    </p>
                  </Link>
                  <span className="mx-2 shrink-0 self-start whitespace-nowrap rounded bg-amber-100 px-2.5 py-1 text-sm font-medium text-amber-900">
                    {displayStatus(shipment.status)}
                  </span>
                </div>

                <div className="mt-3 flex items-center justify-between gap-3 px-2">
                  <p className="text-sm text-slate-500">
                    {shipment.consignments.length} consignments
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleDeleteShipment(shipment)}
                    disabled={deletingShipmentId === shipment.id}
                    className="rounded border border-red-200 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
                  >
                    {deletingShipmentId === shipment.id ? "Deleting..." : "Delete"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
