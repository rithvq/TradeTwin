"use client";

import Link from "next/link";
import { ArrowLeft, RefreshCw, GitCompareArrows } from "lucide-react";
import { useRouteMemory } from "@/hooks/use-route-memory";
import { CarrierOfferForm } from "@/components/routes/carrier-offer-form";
import type { RecordRow } from "@/lib/state-relations";

const button =
  "inline-flex items-center justify-center gap-2 rounded border px-3 py-2 text-sm font-medium disabled:opacity-50";
const input = "mt-1 block w-full min-w-0 rounded border bg-white p-2 text-sm";

export default function RouteMemory({ shipmentId }: { shipmentId: string }) {
  const controller = useRouteMemory(shipmentId);
  const {
    shipment,
    memory,
    busy,
    message,
    timeValue,
    setTimeValue,
    useHistory,
    setUseHistory,
    autoRefresh,
    setAutoRefresh,
    setSelected,
    run,
    request,
    setMessage,
    decisions,
    decision,
    offers,
  } = controller;

  if (!shipment)
    return (
      <main className="p-6" role="status">
        {message || "Loading shipment..."}
      </main>
    );
  if (!shipment.domestic)
    return (
      <main className="space-y-4 p-6">
        <Link href={`/shipments/${shipmentId}#optimizer`} className="underline">
          Shipment route options
        </Link>
        <p>Route memory currently supports domestic Indian road shipments.</p>
      </main>
    );
  return (
    <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <Link
        href={`/shipments/${shipmentId}#optimizer`}
        className="inline-flex items-center gap-2 text-sm"
      >
        <ArrowLeft size={16} />
        Shipment
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Route memory and decisions</h1>
          <p className="mt-1">{shipment?.shipment_reference}</p>
        </div>
        <button
          className={button}
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await request("/observe", {});
              setMessage("Shipment event history updated.");
            })
          }
        >
          <RefreshCw size={16} />
          Sync movement history
        </button>
      </header>
      <p className="border-l-4 border-teal-600 pl-3 text-sm">
        {memory?.catalog_mode === "reviewed"
          ? "Reviewed catalog"
          : "Demo catalog: booking recommendations disabled"}
        . Carrier offers are reviewer-entered, not live market prices. Estimates
        are not a booking or legal guarantee.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={autoRefresh}
          onChange={(e) => setAutoRefresh(e.target.checked)}
        />
        Monitor this shipment every minute while open
      </label>
      {message && (
        <p role="status" className="break-words font-medium">
          {message}
        </p>
      )}
      <section className="space-y-4 border-t pt-5">
        <h2 className="text-lg font-semibold">Observed corridor history</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th className="p-2">PIN-to-PIN corridor</th>
                <th className="p-2">Observations</th>
                <th className="p-2">Median travel hours</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(memory?.corridors ?? {}).map(([key, v]) => (
                <tr key={key} className="border-t">
                  <td className="p-2">{key.replace(":", " to ")}</td>
                  <td className="p-2">{v.sample_count}</td>
                  <td className="p-2">{v.median_hours}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!Object.keys(memory?.corridors ?? {}).length && (
          <p className="text-sm">
            No paired shipment-level loading and arrival observations recorded.
          </p>
        )}
      </section>
      <section className="space-y-4 border-t pt-5">
        <h2 className="text-lg font-semibold">Carrier offers</h2>
        {offers.map((o) => (
          <div
            key={o.id}
            className="flex flex-wrap items-center justify-between gap-3 border-b py-3"
          >
            <div>
              <p className="font-medium">
                {o.carrier} · {o.reference}
              </p>
              <p className="text-sm">
                INR {o.total_price_inr?.toLocaleString("en-IN")} · Valid until{" "}
                {o.valid_until
                  ? new Date(o.valid_until).toLocaleString()
                  : "Unknown"}
              </p>
            </div>
            <button
              className={button}
              disabled={busy || !memory?.routing_configured}
              onClick={() =>
                void run(async () => {
                  await request(`/offers/${o.id}/refresh-routing`, {});
                  setMessage(
                    "Truck routing snapshot updated. Recompare offers to use it.",
                  );
                })
              }
            >
              <RefreshCw size={16} />
              Refresh truck route
            </button>
          </div>
        ))}
        {!memory?.routing_configured && (
          <p className="text-sm">
            External truck routing is not configured. Carrier duration estimates
            remain available.
          </p>
        )}
        <CarrierOfferForm
          busy={controller.busy}
          form={controller.form}
          setForm={controller.setForm}
          vehicle={controller.vehicle}
          setVehicle={controller.setVehicle}
          places={controller.places}
          setPlaces={controller.setPlaces}
          placeValue={controller.placeValue}
          run={controller.run}
          request={controller.request}
          setMessage={controller.setMessage}
        />
      </section>
      <section className="space-y-4 border-t pt-5">
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-sm font-medium">
            Value of time (INR/hour)
            <input
              className={input}
              type="number"
              min="0"
              max="1000000"
              value={timeValue}
              onChange={(e) => setTimeValue(Number(e.target.value))}
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={useHistory}
              onChange={(e) => setUseHistory(e.target.checked)}
            />
            Consider recent observed durations
          </label>
          <button
            className={button}
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const result = await request<RecordRow>("/evaluate", {
                  value_of_time_inr_per_hour: timeValue,
                  use_observed_history: useHistory,
                });
                setSelected(result.id);
              })
            }
          >
            <GitCompareArrows size={16} />
            Compare current offers
          </button>
        </div>
        <label className="block text-sm font-medium">
          Decision history
          <select
            className={input}
            value={decision?.id ?? ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">No saved decision</option>
            {decisions.map((d) => (
              <option key={d.id} value={d.id}>
                {new Date(d.recorded_at).toLocaleString()} ·{" "}
                {d.inputs_changed ? "Inputs changed" : "Same inputs"}
              </option>
            ))}
          </select>
        </label>
        {decision && (
          <>
            <p className="font-medium">
              {decision.recommended_offer_id
                ? "Best-supported offer identified"
                : "No booking-ready offer"}
            </p>
            <p className="text-sm">{decision.scope}</p>
            <p className="text-sm">
              Unresolved live factors: {decision.unknown_factors?.join(", ")}
            </p>
            {decision.options?.map((o) => (
              <article key={o.offer_id} className="space-y-2 border-t py-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">
                    {o.carrier} · {o.reference}
                  </h3>
                  <span className="font-medium">
                    {decision.recommended_offer_id === o.offer_id
                      ? "Recommended"
                      : o.eligible
                        ? "Eligible"
                        : "Review required"}
                  </span>
                </div>
                <p>
                  INR {o.quoted_price_inr.toLocaleString("en-IN")} ·{" "}
                  {o.duration_hours} h · Time-adjusted cost INR{" "}
                  {o.generalized_cost_inr.toLocaleString("en-IN")}
                </p>
                <p className="text-sm">{o.explanation}</p>
                <a
                  className="break-all text-sm underline"
                  href={o.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {o.source_reference}
                </a>
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {o.blocking_reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
                <details>
                  <summary className="cursor-pointer text-sm">
                    Compliance evidence: {o.compliance.status}
                  </summary>
                  <ul className="space-y-1 text-sm">
                    {o.compliance.applicable_rules.map((r, i) => (
                      <li key={i}>
                        <a
                          href={r.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline"
                        >
                          {r.title} ({r.version})
                        </a>
                      </li>
                    ))}
                  </ul>
                  <p>
                    Missing documents:{" "}
                    {o.compliance.missing_documents.join(", ") ||
                      "None in evaluated rules"}
                  </p>
                </details>
              </article>
            ))}
            <p className="break-all text-xs">
              Input fingerprint: {decision.input_fingerprint}
            </p>
          </>
        )}
      </section>
    </main>
  );
}
