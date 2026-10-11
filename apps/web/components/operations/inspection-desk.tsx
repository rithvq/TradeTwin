"use client";
import { useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Fields } from "@/components/trades/fields";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import {
  type Consignment,
  type Receipt,
  type ReceiptLine,
} from "@/lib/operations";
import { type Values } from "@/lib/trades";
import {
  ActionForm,
  ConsignmentHeader,
  Facts,
  Section,
  reason,
} from "./shared";

export function InspectionDesk({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Consignment>(
    `/consignments/${id}`,
    org,
  );
  const cn = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!cn) return <p role="status">Loading inspection...</p>;
  return (
    <div className="space-y-5">
      <ConsignmentHeader cn={cn} />
      <Section name="Independent inspection">
        {cn.receipts
          ?.filter((r) => r.effective)
          .map((r) => (
            <article key={r.id} className="space-y-5 border-b py-4">
              {r.lines.map((line) => (
                <div key={line.id} className="space-y-3">
                  <Facts
                    values={{
                      goods: cn.items.find(
                        (i) => i.id === line.consignment_item_id,
                      )?.description_snapshot,
                      physically_delivered: `${line.delivered_quantity} ${line.uqc}`,
                      accepted: line.accepted_quantity,
                      rejected: line.rejected_quantity,
                      pending: line.pending_inspection_quantity,
                    }}
                  />
                  {cn.allowed_actions.includes("goods.accept") && (
                    <InspectionForm
                      receipt={r}
                      line={line}
                      reload={resource.reload}
                    />
                  )}{" "}
                  {line.decisions
                    .filter(
                      (d) =>
                        d.entry_type === "DECISION" &&
                        !line.decisions.some(
                          (x) => x.reverses_decision_id === d.id,
                        ),
                    )
                    .map((d) => (
                      <details key={d.id}>
                        <summary className="cursor-pointer text-sm">
                          Decision: accepted {d.accepted_quantity}, rejected{" "}
                          {d.rejected_quantity}
                        </summary>
                        {cn.allowed_actions.includes(
                          "goods.acceptance.reverse",
                        ) && (
                          <ActionForm
                            name="Reverse complete inspection decision"
                            path={`/inspection-decisions/${d.id}/reversals`}
                            specs={reason}
                            reload={resource.reload}
                          />
                        )}
                      </details>
                    ))}
                </div>
              ))}
            </article>
          ))}
      </Section>
      {cn.allowed_actions.includes("dispute.open") && (
        <Section name="Inspection dispute">
          <ActionForm
            name="Open inspection dispute"
            path={`/trades/${cn.trade_id}/disputes`}
            initial={{ consignment_id: cn.id, dispute_type: "QUALITY" }}
            specs={[
              {
                path: "summary",
                label: "Dispute summary",
                kind: "textarea",
                required: true,
              },
              {
                path: "requested_remedy",
                label: "Requested remedy",
                kind: "textarea",
              },
            ]}
            reload={resource.reload}
          />
        </Section>
      )}
    </div>
  );
}
function InspectionForm({
  receipt,
  line,
  reload,
}: {
  receipt: Receipt;
  line: ReceiptLine;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const action = useOperationalMutation(org, reload);
  const [values, setValues] = useState<Values>({
    accepted_quantity: "0",
    rejected_quantity: "0",
  });
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const saved = await action.run(`/receipts/${receipt.id}/acceptances`, {
          decisions: [{ receipt_line_id: line.id, ...values }],
        });
        if (saved)
          setValues({ accepted_quantity: "0", rejected_quantity: "0" });
      }}
    >
      <Fields
        specs={[
          {
            path: "accepted_quantity",
            label: "Accept quantity",
            kind: "decimal",
            required: true,
          },
          {
            path: "rejected_quantity",
            label: "Reject quantity",
            kind: "decimal",
            required: true,
          },
          {
            path: "rejection_reason",
            label: "Rejection reason",
            kind: "select",
            options: [
              "DAMAGE",
              "QUALITY",
              "SPECIFICATION",
              "TEMPERATURE",
              "OTHER",
            ],
          },
          { path: "notes", label: "Inspection notes", kind: "textarea" },
        ]}
        values={values}
        onChange={setValues}
        errors={action.error?.fields}
      />
      {action.error && (
        <p role="alert" className="text-red-800">
          {action.error.code}: {action.error.message}
        </p>
      )}
      <Button disabled={action.pending}>
        <Check className="size-4" />
        Record inspection decision
      </Button>
    </form>
  );
}
