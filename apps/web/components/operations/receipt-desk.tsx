"use client";
import { useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { Fields } from "@/components/trades/fields";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import { type Consignment, type Receipt } from "@/lib/operations";
import { type Values, displayTime } from "@/lib/trades";
import {
  ActionForm,
  ConsignmentHeader,
  Facts,
  Section,
  reason,
} from "./shared";

export function ReceiptDesk({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Consignment>(
    `/consignments/${id}`,
    org,
  );
  const cn = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!cn) return <p role="status">Loading receipt desk...</p>;
  return (
    <div className="space-y-5">
      <ConsignmentHeader cn={cn} />
      <Section name="Physical receipt summary">
        {cn.receipt_summary?.map((line) => (
          <Facts
            key={line.consignment_item_id}
            values={{
              goods: line.description,
              uqc: line.uqc,
              loaded: line.loaded_quantity,
              physically_received: line.received_quantity,
              awaiting_receipt: line.awaiting_receipt_quantity,
              short_after_closure: line.short_quantity,
            }}
          />
        ))}
      </Section>
      {cn.movement_status === "ARRIVED" &&
        cn.allowed_actions.includes("receipt.record") && (
          <Section name="Record incremental receipt">
            <ReceiptForm cn={cn} reload={resource.reload} />
          </Section>
        )}
      <Section name="Receipt history">
        {cn.receipts?.map((r) => (
          <article key={r.id} className="space-y-3 border-b border-line py-4">
            <strong>
              {r.effective ? "Effective receipt" : "Superseded receipt"}
            </strong>
            <p className="text-sm">{displayTime(r.received_at)}</p>
            {r.lines.map((line) => (
              <Facts
                key={line.id}
                values={{
                  quantity: `${line.delivered_quantity} ${line.uqc}`,
                  condition: line.observed_condition,
                  accepted: line.accepted_quantity,
                  rejected: line.rejected_quantity,
                  pending_inspection: line.pending_inspection_quantity,
                }}
              />
            ))}
            {r.effective &&
              cn.movement_status === "ARRIVED" &&
              cn.allowed_actions.includes("receipt.correct") && (
                <details>
                  <summary className="cursor-pointer text-sm text-accent">
                    Correct receipt
                  </summary>
                  <ReceiptForm cn={cn} original={r} reload={resource.reload} />
                </details>
              )}
          </article>
        ))}
      </Section>
      <Section name="Delivery recording">
        {cn.movement_status === "ARRIVED" &&
          cn.allowed_actions.includes("receipt.close") && (
            <ActionForm
              name="Close delivery recording"
              path={`/consignments/${id}/delivery-closures`}
              specs={[
                { path: "notes", label: "Closure notes", kind: "textarea" },
              ]}
              etag={cn.etag}
              reload={resource.reload}
            />
          )}
        {cn.current_delivery_closure_id &&
          cn.allowed_actions.includes("receipt.reopen") && (
            <ActionForm
              name="Reopen delivery recording"
              path={`/delivery-closures/${cn.current_delivery_closure_id}/reopenings`}
              specs={reason}
              etag={cn.etag}
              reload={resource.reload}
            />
          )}{" "}
        {cn.closures?.map((c) => (
          <details key={c.id} className="mt-4">
            <summary className="cursor-pointer text-sm font-medium">
              Closure {displayTime(c.created_at)}
            </summary>
            <pre className="max-h-60 overflow-auto text-xs">
              {JSON.stringify(c.quantity_summary_json, null, 2)}
            </pre>
          </details>
        ))}
      </Section>
    </div>
  );
}

function ReceiptForm({
  cn,
  original,
  reload,
}: {
  cn: Consignment;
  original?: Receipt;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const action = useOperationalMutation(org, reload);
  const [clientId, setClientId] = useState(() => crypto.randomUUID());
  const [values, setValues] = useState<Values>({
    received_at: new Date().toISOString(),
  });
  const [lines, setLines] = useState<Record<string, Values>>(() =>
    Object.fromEntries(
      cn.items.map((i) => [
        i.id,
        {
          delivered_quantity:
            original?.lines.find((l) => l.consignment_item_id === i.id)
              ?.delivered_quantity ?? "",
          observed_condition: "GOOD",
        },
      ]),
    ),
  );
  return (
    <form
      className="space-y-4 pt-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const payload = {
          client_receipt_id: clientId,
          ...values,
          lines: cn.items
            .filter(
              (i) =>
                lines[i.id].delivered_quantity &&
                !/^0(?:\.0+)?$/.test(String(lines[i.id].delivered_quantity)),
            )
            .map((i) => ({
              consignment_item_id: i.id,
              uqc: i.uqc,
              ...lines[i.id],
            })),
        };
        const saved = await action.run(
          original
            ? `/receipts/${original.id}/corrections`
            : `/consignments/${cn.id}/receipts`,
          payload,
          original?.head_etag,
        );
        if (saved) {
          setClientId(crypto.randomUUID());
          setLines(
            Object.fromEntries(
              cn.items.map((i) => [
                i.id,
                { delivered_quantity: "", observed_condition: "GOOD" },
              ]),
            ),
          );
        }
      }}
    >
      <Fields
        values={values}
        onChange={setValues}
        errors={action.error?.fields}
        specs={[
          {
            path: "received_at",
            label: "Received at (IST)",
            kind: "datetime",
            required: true,
          },
          {
            path: "received_package_count",
            label: "Received package count",
            kind: "integer",
          },
          { path: "delivery_reference", label: "Delivery reference" },
          { path: "notes", label: "Receipt notes", kind: "textarea" },
          ...(original ? reason : []),
        ]}
      />
      {cn.items.map((i, index) => (
        <fieldset key={i.id} className="space-y-3 border-t pt-3">
          <legend className="text-sm font-semibold">
            {i.description_snapshot} ({i.uqc})
          </legend>
          <Fields
            specs={[
              {
                path: "delivered_quantity",
                label: `Received quantity: ${i.description_snapshot}`,
                kind: "decimal",
              },
              {
                path: "observed_condition",
                label: "Observed condition",
                kind: "select",
                options: ["GOOD", "DAMAGED", "TEMPERATURE_EXCEPTION", "OTHER"],
              },
              {
                path: "condition_notes",
                label: "Condition notes",
                kind: "textarea",
                maxLength: 1000,
              },
            ]}
            values={lines[i.id]}
            onChange={(value) => setLines({ ...lines, [i.id]: value })}
            errors={action.error?.fields.filter((f) =>
              f.path.startsWith(`lines.${index}`),
            )}
          />
        </fieldset>
      ))}
      {action.error && (
        <p role="alert" className="text-red-800">
          {action.error.code}: {action.error.message}
        </p>
      )}
      <Button disabled={action.pending}>
        <Check className="size-4" />
        {original ? "Append receipt correction" : "Record physical receipt"}
      </Button>
    </form>
  );
}
