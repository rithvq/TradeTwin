"use client";

import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  PackageCheck,
  RefreshCw,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { DomesticShipmentForm as ShipmentForm } from "../components/domestic-shipment-form";
import { apiFetch, deleteShipment, displayStatus, shipmentRoute, type Shipment } from "../lib/shipments";

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

  const consignmentCount = shipments.reduce(
    (total, shipment) => total + shipment.consignments.length,
    0,
  );
  const shipmentsInMotion = shipments.filter(
    (shipment) => shipment.status !== "CREATED",
  ).length;

  return (
    <main className="tt-page">
      <div className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6 lg:py-8">
        <header className="grid gap-6 border-b border-line pb-6 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <p className="tt-kicker">Shipment workspace</p>
            <h1 className="mt-2 text-2xl font-semibold text-ink sm:text-3xl">
              Trade operations
            </h1>
          </div>

          <dl className="grid rounded border border-line bg-soft px-4 py-3 sm:grid-cols-3 sm:px-0">
            <DashboardStat
              icon={Boxes}
              label="Shipments"
              value={loading ? "-" : String(shipments.length)}
            />
            <DashboardStat
              icon={PackageCheck}
              label="Consignments"
              value={loading ? "-" : String(consignmentCount)}
            />
            <DashboardStat
              icon={Activity}
              label="In motion"
              value={loading ? "-" : String(shipmentsInMotion)}
            />
          </dl>
        </header>

        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(430px,2fr)]">
          <div id="create-shipment">
            <ShipmentForm />
          </div>

          <section id="shipment-list" className="tt-panel self-start p-5 sm:p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="tt-kicker">Registry</p>
              <h2 className="mt-1 text-xl font-semibold text-ink">Shipments</h2>
            </div>
            <button
              type="button"
              onClick={() => void loadShipments()}
              className="flex items-center gap-2 rounded border border-line bg-soft px-3 py-2 text-sm font-medium text-secondary hover:bg-soft hover:text-ink"
            >
              <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              Refresh
            </button>
          </div>

          {error ? <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
          {loading ? <p className="mt-5 text-sm text-muted">Loading shipments...</p> : null}

          {!loading && shipments.length === 0 ? (
            <div className="mt-5 rounded border border-dashed border-line px-4 py-10 text-center">
              <Boxes className="mx-auto size-6 text-muted" aria-hidden="true" />
              <p className="mt-3 text-sm text-secondary">No shipments recorded.</p>
            </div>
          ) : null}

          <div className="mt-5 divide-y divide-line">
            {shipments.map((shipment) => (
              <div key={shipment.id} className="py-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <Link
                    href={`/shipments/${shipment.id}`}
                    className="group min-w-0 flex-1 rounded px-2 py-1"
                  >
                    <p className="flex items-center gap-2 font-semibold text-ink">
                      <span className="truncate">{shipment.shipment_reference}</span>
                      <ArrowUpRight
                        className="size-4 shrink-0 text-muted transition-colors group-hover:text-ink"
                        aria-hidden="true"
                      />
                    </p>
                    <p className="mt-1 text-sm text-secondary">
                      {shipmentRoute(shipment)} via{" "}
                      {shipment.transport_mode}
                    </p>
                  </Link>
                  <span className={shipmentStatusClasses(shipment.status)}>
                    {displayStatus(shipment.status)}
                  </span>
                </div>

                <div className="mt-3 flex items-center justify-between gap-3 px-2">
                  <p className="text-sm text-muted">
                    {shipment.consignments.length} consignments
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleDeleteShipment(shipment)}
                    disabled={deletingShipmentId === shipment.id}
                    className="flex items-center gap-2 rounded border border-red-400/20 px-3 py-1.5 text-sm font-medium text-red-800 hover:bg-red-400/10 disabled:cursor-not-allowed disabled:border-line disabled:text-muted"
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                    {deletingShipmentId === shipment.id ? "Deleting..." : "Delete"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
        </div>
      </div>
    </main>
  );
}

function DashboardStat({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="tt-stat flex min-w-[150px] items-center gap-3">
      <span className="flex size-9 shrink-0 items-center justify-center rounded border border-line bg-soft text-ink">
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <div>
        <dt className="text-xs text-muted">{label}</dt>
        <dd className="mt-1 text-xl font-semibold text-ink">{value}</dd>
      </div>
    </div>
  );
}

function shipmentStatusClasses(status: string): string {
  const base =
    "mx-2 shrink-0 self-start whitespace-nowrap rounded border px-2.5 py-1 text-xs font-semibold";
  if (status.includes("UNLOADED")) {
    return `${base} border-amber-300/25 bg-amber-300/10 text-amber-800`;
  }
  if (status === "CREATED") {
    return `${base} border-sky-300/25 bg-sky-300/10 text-sky-800`;
  }
  return `${base} border-teal-300/25 bg-teal-300/10 text-teal-800`;
}
