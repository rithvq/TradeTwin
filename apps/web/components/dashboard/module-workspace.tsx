"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, Boxes, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { StatusBadge } from "@/components/dashboard/orbital-module-card";
import { Button } from "@/components/ui/button";
import { apiFetch, displayStatus, type Shipment } from "@/lib/shipments";
import { cn } from "@/lib/utils";
import type { TradeTwinModule } from "@/types/dashboard";

type WorkspaceProps = {
  module: TradeTwinModule;
  destination: (shipmentId: string) => string;
  actionLabel: string;
};

export function ModuleWorkspace(props: WorkspaceProps) {
  return <Suspense fallback={<p className="p-6">Loading workspace...</p>}>
    <WorkspaceContent {...props} />
  </Suspense>;
}

function WorkspaceContent({
  module,
  destination,
  actionLabel,
}: WorkspaceProps) {
  const params = useSearchParams();
  const Icon = module.icon;
  const shipmentsQuery = useQuery({
    queryKey: ["shipments"],
    queryFn: () => apiFetch<Shipment[]>("/shipments"),
  });
  const shipments = (shipmentsQuery.data ?? []).filter((shipment) =>
    params.get("status") !== "active" ||
    !["DELIVERED", "CANCELLED", "ARCHIVED"].includes(shipment.status),
  );
  function shipmentDestination(shipmentId: string) {
    const action = params.get("action");
    const view = params.get("view");
    const anchors: Record<string, string> = {
      "record-event": "add-event", evaluate: "evaluate", upload: "upload",
      extracted: "extracted", missing: "missing-documents", violations: "violations",
      actions: "violations", events: "timeline", factors: "risk", model: "risk",
    };
    const anchor = anchors[action ?? view ?? ""];
    if (!anchor) return destination(shipmentId);
    const documentPage = ["upload", "extracted"].includes(anchor);
    return `/shipments/${shipmentId}${documentPage ? "/documents" : ""}#${anchor}`;
  }

  return (
    <main className="tt-page">
      <header className="tt-context-header">
        <div className="mx-auto max-w-[1320px] px-4 py-5 sm:px-6">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 text-sm text-secondary hover:text-ink"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
            Dashboard
          </Link>
          <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <span className="flex size-12 shrink-0 items-center justify-center rounded border border-line bg-soft text-ink">
                <Icon className="size-5" aria-hidden="true" />
              </span>
              <div>
                <p className="tt-kicker">TradeTwin module</p>
                <h1 className="mt-1 text-2xl font-semibold text-ink">{module.title}</h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-secondary">
                  {module.description}
                </p>
              </div>
            </div>
            <StatusBadge status={module.status} />
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1320px] px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
          <div>
            <p className="tt-kicker">Shipment context</p>
            <h2 className="mt-1 text-xl font-semibold text-ink">Choose a shipment</h2>
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => void shipmentsQuery.refetch()}
              disabled={shipmentsQuery.isFetching}
            >
              <RefreshCw
                className={cn("size-4", shipmentsQuery.isFetching && "animate-spin")}
                aria-hidden="true"
              />
              Refresh
            </Button>
            {module.id === "shipments" ? (
              <Button asChild>
                <Link href="/dashboard/shipments/new">
                  <Plus className="size-4" aria-hidden="true" />
                  New shipment
                </Link>
              </Button>
            ) : null}
          </div>
        </div>

        {shipmentsQuery.isLoading ? (
          <p className="py-10 text-sm text-muted">Loading shipments...</p>
        ) : null}
        {shipmentsQuery.isError ? (
          <div className="mt-5 border border-red-300/20 bg-red-300/[0.06] p-4 text-sm text-red-800">
            Shipment Service is unavailable. Start the Docker environment and refresh this view.
          </div>
        ) : null}
        {!shipmentsQuery.isLoading && !shipmentsQuery.isError && shipments.length === 0 ? (
          <div className="py-14 text-center">
            <Boxes className="mx-auto size-7 text-muted" aria-hidden="true" />
            <p className="mt-3 text-sm text-secondary">No shipments are available yet.</p>
            <Button asChild className="mt-5">
              <Link href="/dashboard/shipments/new">Create a shipment</Link>
            </Button>
          </div>
        ) : null}

        <div className="divide-y divide-line">
          {shipments.map((shipment) => (
            <article
              key={shipment.id}
              className="grid gap-4 py-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="font-semibold text-ink">{shipment.shipment_reference}</h3>
                  <span className="whitespace-nowrap rounded border border-line bg-soft px-2 py-1 text-xs text-secondary">
                    {displayStatus(shipment.status)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-secondary">
                  {shipment.domestic ? `${shipment.domestic.origin.city} to ${shipment.domestic.destination.city}` : `${shipment.exporter_country} to ${shipment.importer_country}`} via {shipment.transport_mode}
                </p>
                <p className="mt-1 text-xs text-muted">
                  {shipment.consignments.length} consignments · {shipment.route_legs.length} route legs
                </p>
              </div>
              <Button asChild variant="outline" className="w-full justify-between md:w-auto">
                <Link href={shipmentDestination(shipment.id)}>
                  {actionLabel}
                  <ArrowUpRight className="size-4" aria-hidden="true" />
                </Link>
              </Button>
            </article>
          ))}
        </div>
      </div>
    </main>
  );
}
