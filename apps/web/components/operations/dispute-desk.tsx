"use client";
import Link from "next/link";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { type Dispute, title } from "@/lib/operations";
import { displayTime } from "@/lib/trades";
import { ActionForm, Facts, Mode, Section, reason } from "./shared";

export function DisputeDesk({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Dispute>(`/disputes/${id}`, org);
  const d = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!d) return <p role="status">Loading dispute...</p>;
  const open = !["RESOLVED", "WITHDRAWN"].includes(d.status);
  const ownDecision = d.events.some(
    (e) =>
      e.proposal_id === d.active_proposal_id && e.actor_organization_id === org,
  );
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap justify-between gap-3">
        <h2 className="text-xl font-semibold">Dispute workspace</h2>
        <Mode mode={d.execution_mode} />
      </header>
      <Link
        className="text-sm text-accent underline"
        href={`/shipments/trades/${d.trade_id}/operations`}
      >
        Trade operations
      </Link>
      <Facts values={{ status: d.status, ...d.dispute_json }} />
      <Section name="Dispute history">
        <ol className="space-y-4">
          {d.events.map((e) => (
            <li className="border-b py-3" key={e.id}>
              <strong>
                {title(e.event_type)} {e.outcome && `/ ${title(e.outcome)}`}
              </strong>
              <p className="text-sm">{e.text}</p>
              <p className="break-all text-xs text-secondary">
                {displayTime(e.created_at)} / Organisation{" "}
                {e.actor_organization_id}
              </p>
            </li>
          ))}
        </ol>
      </Section>
      {open && d.allowed_actions.includes("dispute.comment") && (
        <Section name="Comments">
          <ActionForm
            name="Record comment"
            path={`/disputes/${id}/comments`}
            specs={[
              {
                path: "text",
                label: "Comment",
                kind: "textarea",
                required: true,
              },
            ]}
            reload={resource.reload}
          />
        </Section>
      )}
      {open && d.allowed_actions.includes("dispute.resolve") && (
        <Section name="Bilateral resolution">
          {d.status === "OPEN" && (
            <ActionForm
              name="Propose resolution"
              path={`/disputes/${id}/resolution-proposals`}
              specs={[
                {
                  path: "outcome",
                  label: "Resolution outcome",
                  kind: "select",
                  options: [
                    "ACKNOWLEDGE_FACTS",
                    "INSPECT_AGAIN",
                    "COMMERCIAL_ADJUSTMENT_REQUESTED",
                    "RETURN_REQUESTED",
                    "OTHER",
                  ],
                  required: true,
                },
                {
                  path: "resolution_text",
                  label: "Resolution text",
                  kind: "textarea",
                  required: true,
                },
              ]}
              reload={resource.reload}
            />
          )}
          {d.active_proposal_id && !ownDecision && (
            <>
              <ActionForm
                name="Accept resolution"
                path={`/disputes/${id}/resolution-decisions`}
                initial={{
                  proposal_id: d.active_proposal_id,
                  decision: "ACCEPT",
                }}
                reload={resource.reload}
              />
              <details>
                <summary className="cursor-pointer text-sm">
                  Reject resolution
                </summary>
                <ActionForm
                  name="Reject resolution"
                  path={`/disputes/${id}/resolution-decisions`}
                  initial={{
                    proposal_id: d.active_proposal_id,
                    decision: "REJECT",
                  }}
                  specs={reason}
                  reload={resource.reload}
                />
              </details>
            </>
          )}
          {d.opened_by_organization_id === org && (
            <details>
              <summary className="cursor-pointer text-sm text-red-800">
                Withdraw unresolved dispute
              </summary>
              <ActionForm
                name="Withdraw dispute"
                path={`/disputes/${id}/withdrawals`}
                specs={reason}
                reload={resource.reload}
              />
            </details>
          )}
        </Section>
      )}
      <p className="text-sm text-secondary">
        A resolution records agreement only. Returns, commercial amendments and
        financial corrections require their separate workflows.
      </p>
    </div>
  );
}
