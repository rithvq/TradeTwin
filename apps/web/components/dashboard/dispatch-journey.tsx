"use client";
import Link from "next/link";
import { useEffect, useRef } from "react";
import {
  useDispatchExpiry,
  useLiveDispatch,
} from "@/hooks/use-dispatch-dashboard";
import type { DispatchAction } from "@/lib/guarded-dispatch";
import type { DispatchJourney as Journey } from "@/lib/dispatch-dashboard";
import { displayTime } from "@/lib/trades";
import { DispatchPanels } from "./dispatch-panels";

export function DispatchJourney({
  id,
  action,
  org,
  onClose,
}: {
  id: string;
  action: DispatchAction;
  org: string;
  onClose: () => void;
}) {
  const resource = useLiveDispatch<Journey>(
    `/consignments/${id}/dispatch-journey?action=${action}`,
    org,
    10_000,
  );
  const journey = resource.data;
  const panelRef = useRef<HTMLElement>(null);
  const loaded = !!journey;
  useEffect(() => {
    if (loaded)
      panelRef.current?.scrollIntoView?.({
        block: "start",
        behavior: "smooth",
      });
  }, [loaded, id, action]);
  const authorization = journey?.stages.find((stage) => stage.number === 5);
  useDispatchExpiry(
    authorization?.status === "ACTIVE"
      ? String(authorization.facts.expires_at ?? "")
      : null,
    journey?.checked_at,
    resource.invalidate,
  );
  return (
    <section
      ref={panelRef}
      id="dispatch-journey-detail"
      aria-label={`${action === "DEPARTED" ? "Departure" : "Pickup"} dispatch journey`}
      className="min-w-0 scroll-mt-24 rounded-xl border border-line bg-surface p-4 sm:p-6"
    >
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-ink">
            {action === "DEPARTED" ? "Departure" : "Pickup"} journey
            {journey ? ` · ${journey.reference}` : ""}
          </h3>
          <p className="mt-1 text-sm text-secondary">
            Read-only overview. Complete approvals and movement in the assigned
            screens.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-line px-3 py-2 text-sm"
        >
          Close journey
        </button>
      </header>
      {resource.error ? (
        <p role="alert">Current status unavailable</p>
      ) : !journey ? (
        <p role="status">Loading current journey…</p>
      ) : (
        <>
          <p className="mb-4 text-xs text-secondary">
            Server checked {displayTime(journey.checked_at)}
            {resource.loading ? " · Refreshing" : ""}
          </p>
          {journey.historical && (
            <p className="mb-4 rounded-lg border border-line bg-soft p-3 text-sm">
              Recorded movement. These records describe the completed action and
              do not grant a new movement permission.
            </p>
          )}
          <DispatchPanels journey={journey} org={org} />
          <nav
            aria-label="Continue dispatch in existing screens"
            className="mt-5 flex flex-wrap gap-3"
          >
            {journey.links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded-md border border-line px-4 py-2 text-sm font-semibold text-accent"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </>
      )}
    </section>
  );
}
