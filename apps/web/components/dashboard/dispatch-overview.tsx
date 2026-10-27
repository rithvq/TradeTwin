"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  useDispatchExpiry,
  useDispatchOrganization,
  useLiveDispatch,
} from "@/hooks/use-dispatch-dashboard";
import {
  DISPATCH_CHANGED,
  dispatchLabel,
  type DispatchDashboard,
} from "@/lib/dispatch-dashboard";
import type { DispatchAction } from "@/lib/guarded-dispatch";
import { displayTime } from "@/lib/trades";
import { DispatchJourney } from "./dispatch-journey";
import { DispatchStatus } from "./dispatch-panel-shared";

export function DispatchOverview() {
  const profile = useDispatchOrganization();
  const [cursor, setCursor] = useState("");
  const [selection, select] = useState<{
    id: string;
    action: DispatchAction;
    org: string;
  } | null>(null);
  const resource = useLiveDispatch<DispatchDashboard>(
    `/dispatch-dashboard?limit=20${cursor ? `&cursor=${cursor}` : ""}`,
    profile.org,
    30_000,
  );
  const data = resource.data;
  useEffect(() => {
    setCursor("");
    select(null);
  }, [profile.org]);
  const expiry =
    data?.items
      .filter((item) => item.state === "READY" && item.expires_at)
      .map((item) => item.expires_at!)
      .sort()[0] ?? null;
  useDispatchExpiry(expiry, data?.checked_at, resource.invalidate);
  const unavailable = profile.error || resource.error;
  return (
    <section
      aria-labelledby="dispatch-control-title"
      className="mx-4 mb-8 mt-6 min-w-0 space-y-5 rounded-xl border border-line bg-surface p-4 sm:mx-6 sm:p-6"
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2
            id="dispatch-control-title"
            className="mt-1 text-2xl font-semibold text-ink"
          >
            Dispatch control
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-secondary">
            Track pickup and departure readiness.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {profile.me && (
            <label className="text-xs font-medium text-secondary">
              Organisation
              <select
                aria-label="Dispatch organisation"
                value={profile.org}
                onChange={(event) => profile.setOrg(event.target.value)}
                className="mt-1 block max-w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink"
              >
                <option value="" disabled>
                  Select organisation
                </option>
                {profile.me.memberships.map((member) => (
                  <option
                    key={member.organization_id}
                    value={member.organization_id}
                  >
                    {member.legal_name ?? "Organisation"}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            onClick={() => window.dispatchEvent(new Event(DISPATCH_CHANGED))}
            className="rounded-md border border-line px-3 py-2 text-sm font-medium"
          >
            Refresh dispatch
          </button>
        </div>
      </header>
      {unavailable ? (
        <p
          role="alert"
          className="rounded-lg border border-line bg-soft p-4 font-medium text-ink"
        >
          Current status unavailable
        </p>
      ) : !profile.me ? (
        <p role="status">Loading dispatch profile…</p>
      ) : !profile.org ? (
        <p>Create or join an organisation to view dispatch.</p>
      ) : !data ? (
        <p role="status">Loading live dispatch status…</p>
      ) : (
        <>
          <div
            className="grid grid-cols-2 gap-3 lg:grid-cols-4"
            aria-label="Live dispatch counts"
          >
            {(
              [
                ["Ready to move", data.counts.ready_to_move],
                [
                  "Awaiting evidence or review",
                  data.counts.awaiting_evidence_or_review,
                ],
                ["Expiring soon", data.counts.expiring_soon],
                ["Blocked", data.counts.blocked],
              ] as const
            ).map(([label, count]) => (
              <div
                key={label}
                className="rounded-lg border border-line bg-soft p-4"
              >
                <p className="text-sm font-medium text-secondary">{label}</p>
                <p className="mt-2 text-3xl font-semibold tabular-nums text-ink">
                  {count}
                </p>
              </div>
            ))}
          </div>
          <p className="text-xs text-secondary">
            Server checked {displayTime(data.checked_at)} · Counts cover all
            authorised consignments · Expiring soon: next{" "}
            {data.expiring_within_seconds / 60} minutes
            {resource.loading ? " · Refreshing" : ""}
          </p>
          {!data.items.length ? (
            <p className="py-5 text-sm text-secondary">
              No consignments available for this organisation and your current
              permissions.
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {data.items.map((item) => (
                <li
                  key={item.consignment_id}
                  className="flex min-w-0 flex-col gap-4 py-5 lg:flex-row lg:items-start lg:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-3">
                      <h3 className="break-words font-semibold text-ink">
                        {item.reference}
                      </h3>
                      <DispatchStatus value={item.state} />
                      <span className="text-xs text-secondary">
                        {item.execution_mode}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-secondary">
                      {item.trade_reference} ·{" "}
                      {item.action === "DEPARTED" ? "Departure" : "Pickup"} ·{" "}
                      {item.movement_status.toLowerCase().replaceAll("_", " ")}
                    </p>
                    <p className="mt-2 text-sm capitalize text-ink">
                      Stage: {dispatchLabel(item.current_stage)}
                    </p>
                    {!!item.reason_codes.length && (
                      <p className="mt-1 break-words text-sm capitalize text-secondary">
                        Reason:{" "}
                        {item.reason_codes.map(dispatchLabel).join(", ")}
                      </p>
                    )}
                    <p className="mt-2 text-xs text-secondary">
                      Checked {displayTime(item.checked_at)}
                      {item.expires_at
                        ? ` · Authorization expires ${displayTime(item.expires_at)}`
                        : item.state === "MOVED"
                          ? " · Historical movement"
                          : " · Authorization not issued"}
                    </p>
                    {item.links.map((link) => (
                      <Link
                        key={link.href}
                        href={link.href}
                        className="mr-4 mt-2 inline-block text-sm font-medium text-accent underline"
                      >
                        {link.label}
                      </Link>
                    ))}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {(["PICKUP_CONFIRMED", "DEPARTED"] as const).map(
                      (action) => (
                        <button
                          key={action}
                          type="button"
                          aria-label={`${action === "DEPARTED" ? "Departure" : "Pickup"} journey for ${item.reference}`}
                          onClick={() =>
                            select({
                              id: item.consignment_id,
                              action,
                              org: profile.org,
                            })
                          }
                          className="rounded-md border border-line px-3 py-2 text-sm font-semibold"
                        >
                          {action === "DEPARTED" ? "Departure" : "Pickup"}{" "}
                          journey
                        </button>
                      ),
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {(cursor || data.next_cursor) && (
            <div className="flex gap-3">
              {cursor && (
                <button
                  type="button"
                  onClick={() => setCursor("")}
                  className="rounded-md border border-line px-3 py-2 text-sm"
                >
                  First page
                </button>
              )}
              {data.next_cursor && (
                <button
                  type="button"
                  onClick={() => setCursor(data.next_cursor!)}
                  className="rounded-md border border-line px-3 py-2 text-sm"
                >
                  Next page
                </button>
              )}
            </div>
          )}
        </>
      )}
      {!unavailable && selection && selection.org === profile.org && (
        <DispatchJourney
          key={`${profile.org}:${selection.id}:${selection.action}`}
          id={selection.id}
          action={selection.action}
          org={profile.org}
          onClose={() => select(null)}
        />
      )}
    </section>
  );
}
