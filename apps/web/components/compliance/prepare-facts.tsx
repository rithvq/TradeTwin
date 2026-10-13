"use client";
import { useState } from "react";
import { Save, Send, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationalMutation } from "@/hooks/use-operations";
import { Facts, Section } from "@/components/operations/shared";
import type { ComplianceContext } from "@/lib/guarded-dispatch";
import type { Consignment } from "@/lib/operations";
import type { Values } from "@/lib/trades";
import { PrivateTurnover } from "./private-turnover";

export function PrepareFacts({
  data,
  cn,
  reload,
}: {
  data: ComplianceContext;
  cn: Consignment;
  reload: () => Promise<void>;
}) {
  const { org, refs } = useTradeContext();
  const mutation = useOperationalMutation(org, reload);
  const [values, setValues] = useState<Values>(() =>
    Object.fromEntries(
      Object.entries(data.effective_facts).filter(
        ([k]) =>
          !["field_provenance", "schema_version"].includes(k) &&
          !Object.hasOwn(data.inherited_facts, k),
      ),
    ),
  );
  const [transit, setTransit] = useState<string[] | null>(
    (data.effective_facts.declared_transit_state_codes as string[] | null) ??
      null,
  );
  const [state, setState] = useState("");
  const specs: FieldSpec[] = [
    {
      path: "scope_profile_code",
      label: "Published scope profile",
      kind: "select",
      options: data.available_scope_codes,
    },
    {
      path: "commodity",
      label: "Commodity scope",
      kind: "select",
      options: data.available_commodity_codes,
    },
    {
      path: "requested_pickup_at",
      label: "Requested pickup (IST)",
      kind: "datetime",
    },
    {
      path: "requested_departure_at",
      label: "Requested departure (IST)",
      kind: "datetime",
    },
    {
      path: "expected_arrival_at",
      label: "Expected arrival (IST)",
      kind: "datetime",
    },
    {
      path: "corridor_declaration_basis",
      label: "Corridor basis",
      kind: "select",
      options: ["CARRIER_DECLARATION", "SUPPORTED_ROUTE_RECORD", "UNKNOWN"],
    },
    {
      path: "seller_taxpayer_category_code",
      label: "Seller taxpayer category",
      kind: "select",
      options: ["REGULAR", "UNKNOWN"],
    },
    {
      path: "recipient_category_code",
      label: "Recipient category",
      kind: "select",
      options: ["REGISTERED_REGULAR", "UNKNOWN"],
    },
    {
      path: "supply_taxability",
      label: "Supply taxability",
      kind: "select",
      options: ["TAXABLE", "EXEMPT", "NON_GST", "MIXED", "UNKNOWN"],
    },
    {
      path: "odc",
      label: "Over-dimensional cargo",
      kind: "select",
      options: { YES: "Yes", NO: "No", UNKNOWN: "Unknown" },
    },
    {
      path: "special_valuation_profile",
      label: "Special valuation",
      kind: "select",
      options: ["NONE_DECLARED", "IDENTIFIED_SPECIAL_PROFILE", "UNKNOWN"],
    },
    {
      path: "reverse_charge_position",
      label: "Reverse charge",
      kind: "select",
      options: ["YES", "NO", "UNKNOWN"],
    },
    {
      path: "document_issue_scenario",
      label: "Invoice issue scenario",
      kind: "select",
      options: [
        "ONE_INVOICE_PER_CONSIGNMENT",
        "ONE_INVOICE_MULTIPLE_DISPATCHES",
        "OTHER",
        "UNKNOWN",
      ],
    },
    {
      path: "declaration_note",
      label: "Declaration basis / unresolved information",
      kind: "textarea",
    },
  ];
  async function save(submit: boolean) {
    const { commodity, odc, ...facts } = values;
    await mutation.run(
      `/consignments/${cn.id}/compliance-fact-revisions`,
      {
        expected_context_version: data.context_version,
        submit_for_review: submit,
        facts: {
          ...facts,
          schema_version: 1,
          declared_transit_state_codes: transit,
          commodity_scope_codes: commodity
            ? [commodity]
            : (data.effective_facts.commodity_scope_codes ?? []),
          over_dimensional_cargo_declared:
            odc === "YES" ? true : odc === "NO" ? false : null,
        },
      },
      data.etag,
    );
  }
  return (
    <Section name="Prepare compliance">
      <Facts values={data.inherited_facts} />
      {data.capabilities.includes("turnover.read") && (
        <PrivateTurnover
          data={data}
          onSelect={(id) =>
            setValues({ ...values, seller_turnover_declaration_id: id })
          }
          reload={reload}
        />
      )}
      <Fields
        specs={specs}
        values={values}
        onChange={setValues}
        errors={mutation.error?.fields}
      />
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold">
          Intermediate states, in order
        </legend>
        {transit === null && (
          <p className="text-sm text-amber-900">Corridor not declared</p>
        )}
        <ol className="flex flex-wrap gap-2">
          {transit?.map((code, index) => (
            <li
              key={code}
              className="flex items-center gap-2 border px-3 py-2 text-sm"
            >
              {index + 1}. {refs.states[code]}
              <button
                type="button"
                title="Remove transit state"
                aria-label={`Remove ${refs.states[code]}`}
                onClick={() => setTransit(transit.filter((s) => s !== code))}
              >
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="Add intermediate state"
            value={state}
            onChange={(e) => setState(e.target.value)}
            className="min-w-0 rounded border p-2 text-sm"
          >
            <option value="">Choose state</option>
            {Object.entries(refs.states)
              .filter(
                ([code]) =>
                  ![
                    String(data.inherited_facts.origin_state_code),
                    String(data.inherited_facts.destination_state_code),
                    ...(transit ?? []),
                  ].includes(code),
              )
              .map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
          </select>
          <Button
            variant="outline"
            disabled={!state}
            onClick={() => {
              setTransit([...(transit ?? []), state]);
              setState("");
            }}
          >
            <Plus className="size-4" />
            Add state
          </Button>
          <Button variant="outline" onClick={() => setTransit([])}>
            Declare direct corridor
          </Button>
        </div>
      </fieldset>
      {mutation.error && (
        <p role="alert" className="text-sm text-red-800">
          {mutation.error.code}: {mutation.error.message}
        </p>
      )}
      {mutation.saved && <p role="status">{mutation.saved}</p>}
      <div className="flex flex-wrap gap-3">
        <Button
          variant="outline"
          disabled={mutation.pending}
          onClick={() => void save(false)}
        >
          <Save className="size-4" />
          Save declaration draft
        </Button>
        <Button disabled={mutation.pending} onClick={() => void save(true)}>
          <Send className="size-4" />
          Submit declaration for review
        </Button>
      </div>
    </Section>
  );
}

export function LoadingManifest({
  data,
  cn,
  reload,
}: {
  data: ComplianceContext;
  cn: Consignment;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const action = useOperationalMutation(org, reload);
  const [values, setValues] = useState<Values>(
    data.loading_manifest ?? {
      actual_prepared_gross_weight_kg: cn.plan_json.declared_gross_weight_kg,
      actual_prepared_package_count: cn.plan_json.package_count,
      package_type: cn.plan_json.package_type,
      measurement_basis: "DECLARED",
    },
  );
  return (
    <Section name="Prepared loading manifest">
      <Facts
        values={{
          items: cn.items.map((i) => ({
            description: i.description_snapshot,
            quantity: i.allocated_quantity,
            uqc: i.uqc,
          })),
        }}
      />
      <Fields
        specs={[
          {
            path: "actual_prepared_gross_weight_kg",
            label: "Prepared gross weight (kg)",
            kind: "decimal",
          },
          {
            path: "actual_prepared_package_count",
            label: "Prepared package count",
            kind: "integer",
          },
          {
            path: "package_type",
            label: "Package type",
            kind: "select",
            options: [
              "BOX",
              "CARTON",
              "BAG",
              "PALLET",
              "CRATE",
              "DRUM",
              "BUNDLE",
              "BULK",
              "OTHER",
            ],
          },
          {
            path: "measurement_basis",
            label: "Measurement basis",
            kind: "select",
            options: [
              "DECLARED",
              "WEIGHBRIDGE_RECORD",
              "OTHER_REVIEWED_RECORD",
            ],
          },
          { path: "note", label: "Measurement note", kind: "textarea" },
        ]}
        values={values}
        onChange={setValues}
        errors={action.error?.fields}
      />
      {action.error && <p role="alert">{action.error.message}</p>}
      <Button
        disabled={action.pending}
        onClick={() =>
          void action.run(
            `/consignments/${cn.id}/loading-manifest-revisions`,
            {
              expected_context_version: data.context_version,
              manifest: {
                ...values,
                items: cn.items.map((i) => ({
                  consignment_item_id: i.id,
                  trade_line_ref: i.line_ref,
                  loaded_quantity: i.allocated_quantity,
                  uqc: i.uqc,
                })),
              },
            },
            data.etag,
          )
        }
      >
        <Save className="size-4" />
        Record manifest revision
      </Button>
    </Section>
  );
}
