"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  displayTime,
  tradeRequest,
  type Trade,
  type Values,
} from "@/lib/trades";
import { useTradeContext } from "./trade-context";

export function TradeList() {
  const { org, role } = useTradeContext();
  const [items, setItems] = useState<Trade[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  async function load(next?: string) {
    if (!org) return;
    setPending(true);
    setError("");
    try {
      const result = await tradeRequest<{
        items: Trade[];
        next_cursor: string | null;
      }>(
        `/trades?role=${role}${status ? `&status=${status}` : ""}${next ? `&cursor=${next}` : ""}`,
        org,
      );
      setItems((previous) =>
        next ? [...previous, ...result.items] : result.items,
      );
      setCursor(result.next_cursor);
    } catch (problem) {
      setError(
        problem instanceof Error ? problem.message : "Trades unavailable",
      );
    } finally {
      setPending(false);
    }
  }
  useEffect(() => {
    setItems([]);
    void load();
  }, [org, role, status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!org)
    return (
      <p>
        <Link href="/trades/organization" className="text-accent underline">
          Create your business profile
        </Link>{" "}
        to start a commercial agreement.
      </p>
    );
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">
          {role === "SELLER" ? "Sales trades" : "Purchase trades"}
        </h2>
        <div className="flex gap-3">
          <label className="sr-only" htmlFor="trade-status">
            Agreement status filter
          </label>
          <select
            id="trade-status"
            value={status}
            className="rounded border p-2 text-sm"
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">All agreement statuses</option>
            {["DRAFT", "OFFERED", "CONFIRMED", "CANCELLED"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
          <Button
            variant="outline"
            size="icon"
            title="Refresh trades"
            aria-label="Refresh trades"
            disabled={pending}
            onClick={() => void load()}
          >
            <RefreshCw className="size-4" />
          </Button>
        </div>
      </div>
      {error ? (
        <p role="alert" className="text-red-800">
          {error}
        </p>
      ) : null}
      {pending ? (
        <p role="status">Loading trades...</p>
      ) : !items.length ? (
        <p className="py-6 text-sm text-secondary">
          No accessible trades in this view.
        </p>
      ) : null}
      <div className="divide-y divide-line">
        {items.map((trade) => {
          const revision =
            trade.accepted_revision ?? trade.current_candidate_revision;
          const partner = revision?.facts[
            role === "SELLER" ? "bill_to" : "bill_from"
          ] as Values | undefined;
          return (
            <article
              key={trade.trade_id}
              className="grid gap-3 py-5 md:grid-cols-[minmax(0,1fr)_auto]"
            >
              <div>
                <Link
                  href={`/trades/${trade.trade_id}`}
                  className="font-semibold text-accent underline"
                >
                  {trade.reference}
                </Link>
                <p className="mt-1 text-xs font-semibold">
                  {trade.execution_mode}
                </p>
                {trade.accepted_revision && (
                  <Link
                    href={`/shipments/trades/${trade.trade_id}/operations`}
                    className="mt-2 inline-block text-sm text-accent underline"
                  >
                    Trade operations
                  </Link>
                )}
                <p className="mt-1 text-sm">
                  {role === "SELLER" ? "Buyer" : "Seller"}:{" "}
                  {String(
                    partner?.legal_name ??
                      trade.counterparty?.legal_name ??
                      "Unresolved / proposed counterparty",
                  )}{" "}
                  | Revision {revision?.revision_number ?? "-"}
                </p>
                <p className="mt-2 text-sm">
                  <strong>
                    Commercial agreement status: {trade.agreement_status}
                  </strong>
                </p>
                <p className="text-xs text-muted">
                  Dispatch readiness: Not assessed
                </p>
                <p className="mt-1 text-secondary">
                  Action owner:{" "}
                  {trade.next_action_owners
                    ?.map((owner) =>
                      owner.capability.replaceAll("_", " ").toLowerCase(),
                    )
                    .join(" / ") || "No required commercial action"}
                </p>
              </div>
              <div className="text-sm">
                <p>
                  Offer expiry:{" "}
                  {trade.active_offer
                    ? `${displayTime(trade.active_offer.expires_at)} IST`
                    : "No active offer"}
                </p>
                <p className="mt-1">
                  {trade.approval_progress
                    .map((item) => `${item.party_role}: ${item.decision}`)
                    .join(" | ") || "Not offered"}
                </p>
                <p className="mt-2 font-medium">
                  Next action:{" "}
                  {trade.next_actions.join(", ").replaceAll("_", " ") ||
                    "Awaiting other party / authorised operator"}
                </p>
              </div>
            </article>
          );
        })}
      </div>
      {cursor ? (
        <Button
          variant="outline"
          disabled={pending}
          onClick={() => void load(cursor)}
        >
          More trades
        </Button>
      ) : null}
      <Link
        className="block text-sm text-accent underline"
        href="/dashboard/shipments"
      >
        Existing shipment execution workspace
      </Link>
    </div>
  );
}
