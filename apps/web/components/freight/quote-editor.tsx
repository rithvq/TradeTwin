"use client";
import { useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationalMutation } from "@/hooks/use-operations";
import type { Values } from "@/lib/trades";

export function QuoteEditor({
  rfqId,
  initial,
  specs,
  reload,
  onSaved,
}: {
  rfqId: string;
  initial: Values;
  specs: FieldSpec[];
  reload: () => Promise<void>;
  onSaved: (value: unknown) => void;
}) {
  const { org } = useTradeContext();
  const [values, setValues] = useState(initial);
  const action = useOperationalMutation(org, reload);
  const charges = values.charge_components as Values[];
  const terms = values.contingent_charge_terms as Values[];
  return (
    <form
      className="space-y-4"
      onSubmit={async (event) => {
        event.preventDefault();
        const result = await action.run(
          `/freight-rfqs/${rfqId}/quote-revisions`,
          {
            ...values,
            transport_evidence_revision_ids:
              (
                values.transport_evidence_revision_ids as
                  (string | null)[] | undefined
              )?.filter(Boolean) ?? [],
          },
        );
        if (result) onSaved(result);
      }}
    >
      <Fields
        specs={specs}
        values={values}
        onChange={setValues}
        errors={action.error?.fields}
      />
      {charges.slice(1).map((charge, offset) => {
        const index = offset + 1;
        return (
          <fieldset
            key={String(charge.component_id)}
            className="space-y-3 border-t pt-3"
          >
            <legend className="font-medium">
              Additional fixed charge {index}
            </legend>
            <Fields
              values={values}
              onChange={setValues}
              specs={[
                {
                  path: `charge_components.${index}.component_code`,
                  label: "Charge category",
                  kind: "select",
                  options: [
                    "TOLL",
                    "FUEL_SURCHARGE",
                    "LOADING",
                    "UNLOADING",
                    "HANDLING",
                    "INSURANCE",
                    "OTHER",
                  ],
                },
                {
                  path: `charge_components.${index}.label`,
                  label: "Charge label",
                  required: true,
                },
                {
                  path: `charge_components.${index}.amount_minor`,
                  label: "Fixed amount (paise)",
                  kind: "decimal",
                  required: true,
                },
              ]}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              title="Remove fixed charge"
              aria-label="Remove fixed charge"
              onClick={() =>
                setValues({
                  ...values,
                  charge_components: charges.filter((_, i) => i !== index),
                })
              }
            >
              <Trash2 className="size-4" />
            </Button>
          </fieldset>
        );
      })}
      <Button
        type="button"
        variant="outline"
        disabled={charges.length >= 20}
        onClick={() =>
          setValues({
            ...values,
            charge_components: [
              ...charges,
              {
                component_id: crypto.randomUUID(),
                component_code: "OTHER",
                label: "",
                amount_minor: "0",
              },
            ],
          })
        }
      >
        <Plus className="size-4" />
        Fixed charge
      </Button>
      {terms.map((term, index) => (
        <fieldset key={String(term.code)} className="space-y-3 border-t pt-3">
          <legend className="font-medium">
            {String(term.code).replaceAll("_", " ")}
          </legend>
          <Fields
            values={values}
            onChange={setValues}
            specs={[
              {
                path: `contingent_charge_terms.${index}.free_minutes`,
                label: "Free wait (minutes)",
                kind: "integer",
              },
              {
                path: `contingent_charge_terms.${index}.billing_increment_minutes`,
                label: "Billing increment (minutes)",
                kind: "integer",
                required: true,
              },
              {
                path: `contingent_charge_terms.${index}.charge_per_increment_gross_minor`,
                label: "Gross charge per increment (paise)",
                kind: "decimal",
                required: true,
              },
              {
                path: `contingent_charge_terms.${index}.maximum_charge_gross_minor`,
                label: "Gross cap (paise)",
                kind: "decimal",
              },
              {
                path: `contingent_charge_terms.${index}.applicability_note`,
                label: "Waiting-charge terms",
                kind: "textarea",
                required: true,
              },
            ]}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            title="Remove waiting term"
            aria-label="Remove waiting term"
            onClick={() =>
              setValues({
                ...values,
                contingent_charge_terms: terms.filter((_, i) => i !== index),
              })
            }
          >
            <Trash2 className="size-4" />
          </Button>
        </fieldset>
      ))}
      <div className="flex flex-wrap gap-2">
        {["ORIGIN_WAIT", "DESTINATION_WAIT"]
          .filter((code) => !terms.some((t) => t.code === code))
          .map((code) => (
            <Button
              key={code}
              type="button"
              variant="outline"
              onClick={() =>
                setValues({
                  ...values,
                  contingent_charge_terms: [
                    ...terms,
                    {
                      code,
                      free_minutes: 30,
                      billing_increment_minutes: 15,
                      charge_per_increment_gross_minor: "0",
                      applicability_note: "",
                    },
                  ],
                })
              }
            >
              <Plus className="size-4" />
              {code === "ORIGIN_WAIT"
                ? "Origin wait term"
                : "Destination wait term"}
            </Button>
          ))}
      </div>
      {action.error && (
        <p role="alert">
          {action.error.code}: {action.error.message}
        </p>
      )}
      <Button disabled={action.pending}>
        <Save className="size-4" />
        Save exact carrier offer
      </Button>
    </form>
  );
}
