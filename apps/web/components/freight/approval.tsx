"use client";
import { useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { Fields } from "@/components/trades/fields";
import { useOperationalMutation } from "@/hooks/use-operations";
import { type FreightSelection } from "@/lib/freight";
import { type Values } from "@/lib/trades";

const labels: Record<string, string> = {
  ESTIMATE_NOT_GUARANTEE: "Cost and arrival estimates are not guarantees",
  AVAILABILITY_NOT_RESERVATION: "Resource availability is not a reservation",
  FRESH_PHASE4_RELEASE_REQUIRED:
    "Fresh Phase 4 release is required before movement",
};
export function FreightApproval({
  selection,
  role,
  reload,
}: {
  selection: FreightSelection;
  role: "payer" | "coordinator";
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const mutation = useOperationalMutation(org, reload);
  const [values, setValues] = useState<Values>({
    decision: "APPROVE",
    reason: "",
  });
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  if (selection.decisions.some((d) => d.role === role.toUpperCase()))
    return null;
  const ready =
    values.decision === "REJECT" ||
    selection.proposal.acknowledged_limitations_required.every((code) =>
      acknowledged.includes(code),
    );
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        void mutation.run(
          `/tradetwin-selections/${selection.id}/${role}-decisions`,
          {
            ...values,
            proposal_hash: selection.proposal_hash,
            quote_hash: selection.quote_hash,
            acknowledged_limitation_codes: acknowledged,
          },
          selection.etag,
        );
      }}
    >
      <Fields
        specs={[
          {
            path: "decision",
            label:
              role === "payer"
                ? "Procurement decision"
                : "Operational decision",
            kind: "select",
            options: ["APPROVE", "REJECT"],
          },
          { path: "reason", label: "Reason", kind: "textarea", required: true },
        ]}
        values={values}
        onChange={setValues}
        errors={mutation.error?.fields}
      />
      {selection.proposal.acknowledged_limitations_required.map((code) => (
        <label
          key={code}
          className="flex items-center gap-2 text-sm font-medium"
        >
          <input
            type="checkbox"
            checked={acknowledged.includes(code)}
            onChange={(e) =>
              setAcknowledged(
                e.target.checked
                  ? [...acknowledged, code]
                  : acknowledged.filter((c) => c !== code),
              )
            }
          />
          {labels[code] ?? code}
        </label>
      ))}
      {mutation.error && (
        <p role="alert">
          {mutation.error.code}: {mutation.error.message}
        </p>
      )}
      <Button disabled={mutation.pending || !ready}>
        <Check className="size-4" />
        {role === "payer"
          ? "Approve exact freight offer"
          : "Approve operational plan"}
      </Button>
    </form>
  );
}
