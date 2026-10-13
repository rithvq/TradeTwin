"use client";
import { useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import { type FreightContext } from "@/lib/freight";
import {
  ActionForm,
  Facts,
  Section,
  reason,
} from "@/components/operations/shared";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import type { Values } from "@/lib/trades";

export function FreightCosts({
  context,
  reload,
}: {
  context: FreightContext;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<{
    items: { id: string; assumptions_json: Values; review_decision: string }[];
  }>(`/consignments/${context.consignment_id}/tradetwin-cost-assumptions`, org);
  const [quote, setQuote] = useState("");
  const quotes = context.rfqs.flatMap((r) => r.quotes);
  return (
    <Section name="Private freight-payer cost declarations">
      {context.capabilities.includes("tradetwin.cost_assumptions.prepare") && (
        <>
          <label className="text-sm font-medium">
            Applies to offer
            <select
              className="ml-2 rounded border p-2"
              value={quote}
              onChange={(e) => setQuote(e.target.value)}
            >
              <option value="">Choose offer</option>
              {quotes.map((q) => (
                <option key={q.id} value={q.id}>
                  {q.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {quote && (
            <CostDeclaration
              key={quote}
              consignmentId={context.consignment_id}
              initial={{
                comparison_policy: "ALLOW_DECLARED_ESTIMATES",
                external_cost_components: [
                  {
                    component_id: crypto.randomUUID(),
                    category: "LOADING",
                    label: "External loading",
                    applies_to_quote_revision_ids: [quote],
                    basis: "FIXED",
                    fixed_amount_minor: null,
                    quantity_source: "FIXED",
                    amount_includes_applicable_tax: false,
                    source_kind: "USER_ESTIMATE",
                  },
                ],
                recipient_tax_cash_estimates:
                  quotes.find((q) => q.id === quote)?.quote_json
                    .tax_treatment === "DECLARED_RECIPIENT_ACCOUNTED"
                    ? [
                        {
                          quote_revision_id: quote,
                          amount_minor: null,
                          basis_document_version_ids: [],
                          declaration_note: "",
                        },
                      ]
                    : [],
              }}
              specs={costSpecs}
              reload={async () => {
                await resource.reload();
                await reload();
              }}
            />
          )}
        </>
      )}
      {resource.error && <p role="alert">{resource.error}</p>}
      {resource.data?.items.map((a) => (
        <details key={a.id} className="border-b py-3">
          <summary className="cursor-pointer font-medium">
            Declaration {a.id.slice(0, 8)} / {a.review_decision}
          </summary>
          <p className="my-2 break-all text-xs">Revision: {a.id}</p>
          <Facts values={a.assumptions_json} />
          {context.capabilities.includes(
            "tradetwin.cost_assumptions.review",
          ) && (
            <ActionForm
              name="Review cost declaration"
              path={`/tradetwin-cost-assumption-revisions/${a.id}/reviews`}
              initial={{ decision: "APPROVE_DECLARATION" }}
              specs={[
                {
                  path: "decision",
                  label: "Independent review",
                  kind: "select",
                  options: ["APPROVE_DECLARATION", "RETURN_FOR_CORRECTION"],
                },
                ...reason,
              ]}
              reload={async () => {
                await resource.reload();
                await reload();
              }}
            />
          )}
        </details>
      ))}
    </Section>
  );
}
function CostDeclaration({
  consignmentId,
  initial,
  specs,
  reload,
}: {
  consignmentId: string;
  initial: Values;
  specs: FieldSpec[];
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const action = useOperationalMutation(org, reload);
  const [values, setValues] = useState(initial);
  const components = values.external_cost_components as Values[];
  const tax = values.recipient_tax_cash_estimates as Values[];
  return (
    <form
      className="space-y-4"
      onSubmit={async (event) => {
        event.preventDefault();
        await action.run(
          `/consignments/${consignmentId}/tradetwin-cost-assumption-revisions`,
          values,
        );
      }}
    >
      {components.map((component, index) => (
        <fieldset
          key={String(component.component_id)}
          className="space-y-3 border-t py-3"
        >
          <legend className="font-medium">Additional cost {index + 1}</legend>
          <Fields
            specs={specs.map((spec) => ({
              ...spec,
              path: spec.path.replace(
                "external_cost_components.0.",
                `external_cost_components.${index}.`,
              ),
            }))}
            values={values}
            onChange={setValues}
            errors={action.error?.fields}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            title="Remove cost component"
            aria-label="Remove cost component"
            onClick={() =>
              setValues({
                ...values,
                external_cost_components: components.filter(
                  (_, i) => i !== index,
                ),
              })
            }
          >
            <Trash2 className="size-4" />
          </Button>
        </fieldset>
      ))}
      <Button
        type="button"
        variant="outline"
        disabled={components.length >= 30}
        onClick={() =>
          setValues({
            ...values,
            external_cost_components: [
              ...components,
              {
                ...(initial.external_cost_components as Values[])[0],
                component_id: crypto.randomUUID(),
                label: "Additional logistics estimate",
              },
            ],
          })
        }
      >
        <Plus className="size-4" />
        Additional cost
      </Button>
      {!!tax.length && (
        <Fields
          values={values}
          onChange={setValues}
          specs={[
            {
              path: "recipient_tax_cash_estimates.0.amount_minor",
              label: "Declared recipient-tax cash estimate (paise)",
              kind: "decimal",
            },
            {
              path: "recipient_tax_cash_estimates.0.declaration_note",
              label: "Recipient-tax declaration basis",
              kind: "textarea",
              required: true,
            },
          ]}
        />
      )}
      {action.error && (
        <p role="alert">
          {action.error.code}: {action.error.message}
        </p>
      )}
      <Button disabled={action.pending}>
        <Save className="size-4" />
        Save cost declaration
      </Button>
    </form>
  );
}
const costSpecs: FieldSpec[] = [
  {
    path: "external_cost_components.0.category",
    label: "Additional cost category",
    kind: "select",
    options: [
      "TOLL",
      "FUEL_SURCHARGE",
      "LOADING",
      "UNLOADING",
      "HANDLING",
      "CARGO_INSURANCE",
      "OTHER",
    ],
  },
  {
    path: "external_cost_components.0.label",
    label: "Cost label",
    required: true,
  },
  {
    path: "external_cost_components.0.basis",
    label: "Calculation basis",
    kind: "select",
    options: ["FIXED", "PER_KM", "PER_KG", "PER_PACKAGE"],
  },
  {
    path: "external_cost_components.0.fixed_amount_minor",
    label: "Fixed gross amount (paise)",
    kind: "decimal",
  },
  {
    path: "external_cost_components.0.rate_minor_per_unit",
    label: "Rate (paise per unit)",
    kind: "decimal",
  },
  {
    path: "external_cost_components.0.quantity_source",
    label: "Exact quantity source",
    kind: "select",
    options: ["FIXED", "ROUTE_DISTANCE_KM", "CARGO_GROSS_KG", "PACKAGE_COUNT"],
  },
  {
    path: "external_cost_components.0.amount_includes_applicable_tax",
    label: "Declared amount includes applicable tax",
    kind: "boolean",
  },
  {
    path: "external_cost_components.0.valid_until",
    label: "Estimate valid until (IST)",
    kind: "datetime",
  },
  {
    path: "external_cost_components.0.note",
    label: "Source and limitations",
    kind: "textarea",
    required: true,
  },
];
