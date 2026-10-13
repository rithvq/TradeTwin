"use client";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import {
  ActionForm,
  Facts,
  Section,
  reason,
} from "@/components/operations/shared";
import type { Values } from "@/lib/trades";

type CancellationDesk = {
  commitment_hash: string;
  role: string;
  can_propose: boolean;
  items: {
    id: string;
    etag: string;
    proposal_hash: string;
    status: string;
    cancellation: Values;
    already_decided: boolean;
  }[];
};
export function FreightCancellation({
  commitmentId,
}: {
  commitmentId: string;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<CancellationDesk>(
    `/freight-commitments/${commitmentId}/cancellation-proposals`,
    org,
  );
  const data = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading cancellation terms...</p>;
  return (
    <Section name="Bilateral pre-pickup freight cancellation">
      {data.can_propose && (
        <ActionForm
          name="Propose cancellation terms"
          path={`/freight-commitments/${commitmentId}/cancellation-proposals`}
          initial={{
            commitment_hash: data.commitment_hash,
            proposed_fee_position: "NO_FEE",
            proposed_fee_minor: "0",
            proposed_fee_note: "No payment or refund is created",
          }}
          specs={[
            ...reason,
            {
              path: "proposed_fee_position",
              label: "Cancellation fee position",
              kind: "select",
              options: ["NO_FEE", "AGREED_AMOUNT"],
            },
            {
              path: "proposed_fee_minor",
              label: "Agreed fee (paise)",
              kind: "decimal",
            },
            {
              path: "proposed_fee_note",
              label: "Fee declaration",
              kind: "textarea",
              required: true,
            },
          ]}
          reload={resource.reload}
        />
      )}
      {data.items.map((c) => (
        <article key={c.id} className="space-y-3 border-b py-3">
          <strong>{c.status}</strong>
          <Facts values={c.cancellation} />
          <p className="break-all text-xs">Proposal hash: {c.proposal_hash}</p>
          {c.status === "PENDING" && !c.already_decided && (
            <ActionForm
              name="Decide cancellation"
              path={`/freight-cancellation-proposals/${c.id}/decisions`}
              etag={c.etag}
              initial={{
                proposal_hash: c.proposal_hash,
                decision_role: data.role,
                decision: "APPROVE",
              }}
              specs={[
                {
                  path: "decision",
                  label: "Cancellation decision",
                  kind: "select",
                  options: ["APPROVE", "REJECT"],
                },
                ...reason,
              ]}
              reload={resource.reload}
            />
          )}
        </article>
      ))}
    </Section>
  );
}
