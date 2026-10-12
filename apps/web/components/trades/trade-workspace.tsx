"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Edit, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  displayTime,
  tradeRequest,
  type EvidenceEvent,
  type Trade,
} from "@/lib/trades";
import { AgreementView } from "./agreement-view";
import { useTradeContext } from "./trade-context";
import { DocumentModulePanel } from "@/components/document-desk/module-panel";

const modules = [
  "Shipments",
  "Documents",
  "Compliance",
  "Graph",
  "Risk",
  "Optimizer",
  "Regulations",
  "Evidence",
];
export function TradeWorkspace({ tradeId }: { tradeId: string }) {
  const { org } = useTradeContext();
  const [trade, setTrade] = useState<Trade | null>(null);
  const [events, setEvents] = useState<EvidenceEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [pending, setPending] = useState(false);
  const [activeModule, setActiveModule] = useState("Shipments");
  const [evidenceError, setEvidenceError] = useState("");
  async function history(next?: string) {
    try {
      const result = await tradeRequest<{
        items: EvidenceEvent[];
        next_cursor: string | null;
      }>(
        `/trades/${tradeId}/evidence-events${next ? `?cursor=${next}` : ""}`,
        org,
      );
      setEvents((previous) =>
        next ? [...previous, ...result.items] : result.items,
      );
      setCursor(result.next_cursor);
      setEvidenceError("");
    } catch (problem) {
      setEvidenceError(
        problem instanceof Error ? problem.message : "Evidence not accessible",
      );
    }
  }
  async function load() {
    if (!org) return;
    try {
      setTrade(await tradeRequest<Trade>(`/trades/${tradeId}`, org));
      setError("");
      await history();
    } catch (problem) {
      setTrade(null);
      setError(
        problem instanceof Error ? problem.message : "Trade unavailable",
      );
    }
  }
  useEffect(() => {
    setTrade(null);
    setEvents([]);
    setReviewed(false);
    void load();
  }, [org, tradeId]); // eslint-disable-line react-hooks/exhaustive-deps
  async function action(name: string) {
    if (!trade) return;
    setPending(true);
    setError("");
    try {
      const offer = trade.active_offer;
      if (name === "ACCEPT" || name === "REJECT") {
        if (!offer) throw new Error("Reload the current offer");
        await tradeRequest(
          `/offers/${offer.id}/${name === "ACCEPT" ? "confirmations" : "rejections"}`,
          org,
          "POST",
          {
            revision_id: offer.revision_id,
            terms_hash: offer.terms_hash,
            ...(name === "REJECT" ? { reason } : {}),
          },
        );
      } else if (name === "WITHDRAW" && offer)
        await tradeRequest(
          `/offers/${offer.id}/withdrawals`,
          org,
          "POST",
          { reason },
          trade.etag,
        );
      else if (name === "PROPOSE_AMENDMENT")
        await tradeRequest(
          `/trades/${tradeId}/amendments`,
          org,
          "POST",
          { base_accepted_revision_id: trade.accepted_revision?.id, reason },
          trade.etag,
        );
      else if (name === "WITHDRAW_AMENDMENT" && trade.pending_amendment)
        await tradeRequest(
          `/amendments/${trade.pending_amendment.id}/withdrawals`,
          org,
          "POST",
          { reason },
        );
      setReviewed(false);
      await load();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Action failed");
    } finally {
      setPending(false);
    }
  }
  if (!org) return <p>Select an organisation to view this trade.</p>;
  return (
    <div className="space-y-6">
      {activeModule !== "Shipments" && trade && (
        <DocumentModulePanel tradeId={tradeId} module={activeModule} />
      )}
      {error ? (
        <p role="alert" className="text-red-800">
          {error}
        </p>
      ) : null}
      {!trade ? (
        <p>Trade unavailable or loading.</p>
      ) : (
        <>
          <div className="flex flex-wrap justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold">{trade.reference}</h2>
              <p className="mt-2 text-xs font-semibold">
                {trade.execution_mode}
              </p>
              {trade.accepted_revision && (
                <Link
                  href={`/shipments/trades/${tradeId}/operations`}
                  className="mt-2 inline-block text-sm font-semibold text-accent underline"
                >
                  Open trade operations
                </Link>
              )}
              <p className="mt-2">
                <strong>
                  Commercial agreement status: {trade.agreement_status}
                </strong>
              </p>
              <p className="text-sm text-secondary">
                Dispatch readiness: Not assessed
              </p>
            </div>
            <Button
              variant="outline"
              aria-label="Refresh agreement"
              title="Refresh agreement"
              size="icon"
              onClick={() => void load()}
            >
              <RefreshCw className="size-4" />
            </Button>
          </div>
          <nav className="flex flex-wrap gap-2" aria-label="Trade modules">
            {modules.map((module) => (
              <button
                key={module}
                onClick={() => setActiveModule(module)}
                aria-current={activeModule === module ? "page" : undefined}
                className={`min-h-10 rounded border px-3 text-sm ${activeModule === module ? "border-accent bg-accent text-white" : "border-line bg-surface"}`}
              >
                {module}
              </button>
            ))}
          </nav>
          {!["Shipments", "Evidence"].includes(activeModule) ? (
            <section className="space-y-3 border-y border-line py-6">
              <h3 className="font-semibold">{activeModule}</h3>
              <p className="text-sm text-secondary">
                No shipment execution is linked to this commercial agreement.{" "}
                {activeModule === "Documents"
                  ? "Document processing"
                  : activeModule === "Risk"
                    ? "Risk assessment"
                    : activeModule === "Optimizer"
                      ? "Route comparison"
                      : activeModule === "Graph"
                        ? "Shipment graph"
                        : activeModule === "Regulations"
                          ? "Regulation impact analysis"
                          : "Compliance assessment"}{" "}
                belongs to a later execution phase. No result has been generated
                for this trade.
              </p>
              <Link
                className="text-sm text-accent underline"
                href={`/dashboard/${activeModule.toLowerCase()}`}
              >
                Open existing {activeModule.toLowerCase()} module
              </Link>
            </section>
          ) : null}
          {activeModule === "Shipments" ? (
            <>
              {trade.accepted_revision ? (
                <AgreementView
                  revision={trade.accepted_revision}
                  title="Accepted commercial agreement"
                />
              ) : null}
              {trade.current_candidate_revision &&
              trade.current_candidate_revision.id !==
                trade.accepted_revision?.id ? (
                <AgreementView
                  revision={trade.current_candidate_revision}
                  title={
                    trade.pending_amendment
                      ? "Pending amendment (not yet agreed)"
                      : "Current candidate / offered terms"
                  }
                />
              ) : null}
              <section className="space-y-4" aria-label="Commercial approvals">
                <h3 className="text-lg font-semibold">Approval progress</h3>
                {trade.active_offer ? (
                  <p className="text-sm">
                    Offer {trade.active_offer.status} | Expires{" "}
                    {displayTime(trade.active_offer.expires_at)} IST
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-4">
                  {trade.approval_progress.map((item) => (
                    <p className="text-sm" key={item.party_role}>
                      <strong>{item.party_role}:</strong> {item.decision}
                    </p>
                  ))}
                </div>
                {trade.next_actions.includes("ACCEPT") ? (
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      className="mt-1"
                      type="checkbox"
                      checked={reviewed}
                      onChange={(event) => setReviewed(event.target.checked)}
                    />
                    I have reviewed the complete offered terms, including the
                    proposed billing address, price basis and unassessed
                    charges.
                  </label>
                ) : null}
                {trade.next_actions.some((item) =>
                  [
                    "REJECT",
                    "WITHDRAW",
                    "PROPOSE_AMENDMENT",
                    "WITHDRAW_AMENDMENT",
                  ].includes(item),
                ) ? (
                  <label className="block text-sm font-medium">
                    Reason (required for rejection, withdrawal or amendment)
                    <textarea
                      rows={3}
                      maxLength={2000}
                      className="mt-1 block w-full rounded border p-3"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                    />
                  </label>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  {trade.next_actions.includes("ACCEPT") ? (
                    <Button
                      disabled={!reviewed || pending}
                      onClick={() => void action("ACCEPT")}
                    >
                      <Check className="size-4" />
                      Accept offered terms
                    </Button>
                  ) : null}
                  {trade.next_actions.includes("REJECT") ? (
                    <Button
                      variant="outline"
                      disabled={!reason.trim() || pending}
                      onClick={() => void action("REJECT")}
                    >
                      <X className="size-4" />
                      Reject terms
                    </Button>
                  ) : null}
                  {trade.next_actions.some((item) =>
                    ["EDIT_DRAFT", "EDIT_AMENDMENT"].includes(item),
                  ) ? (
                    <Button variant="outline" asChild>
                      <Link href={`/trades/${tradeId}/edit`}>
                        <Edit className="size-4" />
                        Resume candidate
                      </Link>
                    </Button>
                  ) : null}
                  {(
                    [
                      ["WITHDRAW", "Withdraw own offer"],
                      ["PROPOSE_AMENDMENT", "Propose amendment"],
                      ["WITHDRAW_AMENDMENT", "Withdraw amendment"],
                    ] as const
                  ).map(([name, label]) =>
                    trade.next_actions.includes(name) ? (
                      <Button
                        key={name}
                        variant="outline"
                        disabled={!reason.trim() || pending}
                        onClick={() => void action(name)}
                      >
                        {label}
                      </Button>
                    ) : null,
                  )}
                </div>
                <p className="text-sm text-secondary">
                  Next action:{" "}
                  {trade.next_actions.join(", ").replaceAll("_", " ") ||
                    "Awaiting another party or authorised operator"}
                </p>
              </section>
            </>
          ) : null}
          {activeModule === "Evidence" ? (
            <section id="trade-evidence" className="space-y-4">
              <h3 className="text-lg font-semibold">Evidence timeline</h3>
              {evidenceError ? <p role="alert">{evidenceError}</p> : null}
              <ol className="divide-y divide-line">
                {events.map((event) => (
                  <li key={event.id} className="py-4">
                    <div className="flex flex-wrap justify-between gap-2">
                      <strong className="text-sm">
                        {event.action.replaceAll("_", " ")}
                      </strong>
                      <time className="text-xs text-muted">
                        {displayTime(event.occurred_at)} IST
                      </time>
                    </div>
                    <p className="mt-1 text-sm">
                      {event.actor_name} | Organisation{" "}
                      <span className="break-all font-mono text-xs">
                        {event.actor_organization_id}
                      </span>
                    </p>
                    <p className="break-all text-xs text-muted">
                      Revision: {event.revision_id ?? "-"} |{" "}
                      {event.subject_type}: {event.subject_id}
                    </p>
                    <dl className="mt-2 space-y-1 text-sm">
                      {Object.entries(event.summary).map(([key, value]) => (
                        <div key={key}>
                          <dt className="inline font-medium">
                            {key.replaceAll("_", " ")}:{" "}
                          </dt>
                          <dd className="inline break-words">
                            {Array.isArray(value)
                              ? value.join(", ")
                              : String(value ?? "-")}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </li>
                ))}
              </ol>
              {cursor ? (
                <Button variant="outline" onClick={() => void history(cursor)}>
                  More history
                </Button>
              ) : null}
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
