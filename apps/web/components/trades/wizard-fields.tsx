"use client";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getValue, setValue, type FieldError, type Values } from "@/lib/trades";
import { Fields, type FieldSpec } from "./fields";

export function goodsSpecs(units: string[]): FieldSpec[] {
  return [
    {
      path: "description",
      label: "Product description",
      required: true,
      maxLength: 500,
    },
    {
      path: "specification",
      label: "Specification",
      kind: "textarea",
      required: true,
    },
    { path: "hsn_code", label: "HSN code (optional)", maxLength: 8 },
    {
      path: "hsn_confirmation",
      label: "HSN declaration",
      kind: "select",
      options: ["NOT_PROVIDED", "SUGGESTED", "USER_CONFIRMED"],
      required: true,
    },
    { path: "quantity", label: "Quantity", kind: "decimal", required: true },
    {
      path: "uqc",
      label: "Unit code",
      kind: "select",
      options: units,
      required: true,
    },
    {
      path: "unit_price_minor",
      label: "Unit price (paise; 100 paise = INR 1)",
      kind: "decimal",
      required: true,
    },
    {
      path: "discount_minor",
      label: "Line discount (integer paise)",
      required: true,
    },
    {
      path: "declared_tax_rate_percent",
      label: "Declared estimated tax rate (%)",
      kind: "decimal",
    },
    {
      path: "estimated_gross_weight_kg",
      label: "Estimated weight (kg)",
      kind: "decimal",
    },
    {
      path: "package_count_estimate",
      label: "Estimated package count",
      kind: "integer",
    },
    ...[
      "hazardous_declared",
      "temperature_controlled",
      "fragile",
      "stackable",
    ].map((path) => ({
      path,
      label: path.replaceAll("_", " "),
      kind: "boolean" as const,
    })),
    {
      path: "temperature_min_c",
      label: "Minimum temperature (C)",
      kind: "decimal",
    },
    {
      path: "temperature_max_c",
      label: "Maximum temperature (C)",
      kind: "decimal",
    },
  ];
}
export const commercialSpecs: FieldSpec[] = [
  {
    path: "pricing_basis",
    label: "Price basis",
    kind: "select",
    options: ["NET_TAX_EXTRA", "GROSS_TAX_INCLUDED"],
    required: true,
  },
  {
    path: "tax_terms",
    label: "Agreed tax terms (declaration, not final tax treatment)",
    kind: "textarea",
    required: true,
    maxLength: 1000,
  },
  ...(
    [
      ["freight_payer", "Freight payer", ["SELLER", "BUYER", "SHARED"]],
      [
        "loading_responsibility",
        "Loading responsibility",
        ["SELLER", "BUYER", "CARRIER"],
      ],
      [
        "unloading_responsibility",
        "Unloading responsibility",
        ["SELLER", "BUYER", "CARRIER"],
      ],
      [
        "insurance_responsibility",
        "Insurance responsibility",
        ["SELLER", "BUYER", "CARRIER", "NONE"],
      ],
      [
        "payment_mode",
        "Payment mode",
        ["ADVANCE", "ON_DELIVERY", "CREDIT", "MILESTONE"],
      ],
    ] as [string, string, string[]][]
  ).map(([path, label, options]) => ({
    path: `commercial_terms.${path}`,
    label,
    kind: "select" as const,
    options,
    required: true,
  })),
  {
    path: "commercial_terms.seller_freight_share_percent",
    label: "Seller freight share (%) when shared",
    kind: "decimal",
  },
  {
    path: "commercial_terms.freight_included_in_goods_price",
    label: "Freight included in goods price",
    kind: "boolean",
  },
  {
    path: "commercial_terms.freight_estimate_minor",
    label: "Separate freight estimate (integer paise)",
  },
  {
    path: "commercial_terms.insurance_required",
    label: "Insurance required",
    kind: "boolean",
  },
  { path: "commercial_terms.advance_minor", label: "Advance (integer paise)" },
  {
    path: "commercial_terms.credit_days",
    label: "Credit days",
    kind: "integer",
  },
  {
    path: "commercial_terms.acceptance_window_hours",
    label: "Quality acceptance window (hours)",
    kind: "integer",
    required: true,
  },
  ...["quality_acceptance_criteria", "return_policy", "cancellation_terms"].map(
    (path) => ({
      path: `commercial_terms.${path}`,
      label: path.replaceAll("_", " "),
      kind: "textarea" as const,
      required: true,
    }),
  ),
  ...[
    "partial_delivery_allowed",
    "supplier_substitution_allowed",
    "pickup_location_substitution_allowed",
  ].map((path) => ({
    path: `commercial_terms.${path}`,
    label: path.replaceAll("_", " "),
    kind: "boolean" as const,
  })),
  {
    path: "commercial_terms.commercial_valid_until",
    label: "Offer expiration (IST)",
    kind: "datetime",
    required: true,
  },
];
export const deliverySpecs: FieldSpec[] = [
  ...["pickup_earliest_at", "pickup_latest_at", "delivery_deadline_at"].map(
    (path) => ({
      path: `delivery_requirements.${path}`,
      label: `${path.replaceAll("_", " ")} (IST)`,
      kind: "datetime" as const,
      required: true,
    }),
  ),
  {
    path: "delivery_requirements.receiving_window_start_local",
    label: "Receiving window start (local)",
    kind: "time",
    required: true,
  },
  {
    path: "delivery_requirements.receiving_window_end_local",
    label: "Receiving window end (local)",
    kind: "time",
    required: true,
  },
  {
    path: "delivery_requirements.receiving_timezone",
    label: "Receiving timezone",
    required: true,
  },
  ...[
    "receiving_window_crosses_midnight",
    "consolidation_allowed",
    "return_truck_allowed",
  ].map((path) => ({
    path: `delivery_requirements.${path}`,
    label: path.replaceAll("_", " "),
    kind: "boolean" as const,
  })),
  {
    path: "delivery_requirements.maximum_transshipments",
    label: "Maximum transshipments",
    kind: "integer",
    required: true,
  },
  {
    path: "delivery_requirements.delivery_notes",
    label: "Delivery notes",
    kind: "textarea",
  },
];
export function Milestones({
  facts,
  change,
  errors,
}: {
  facts: Values;
  change: (value: Values) => void;
  errors: FieldError[];
}) {
  const items = (getValue(facts, "commercial_terms.milestone_schedule") ??
    []) as Values[];
  return (
    <section className="space-y-4">
      <h4 className="font-semibold">Payment milestones (quoted goods value)</h4>
      {items.map((item, index) => (
        <div key={index} className="border-t border-line pt-4">
          <Fields
            values={item}
            onChange={(value) =>
              change(
                setValue(
                  facts,
                  "commercial_terms.milestone_schedule",
                  items.map((row, current) =>
                    current === index ? value : row,
                  ),
                ),
              )
            }
            errors={errors
              .filter((error) =>
                error.path.startsWith(
                  `commercial_terms.milestone_schedule.${index}.`,
                ),
              )
              .map((error) => ({
                ...error,
                path: error.path.split(".").slice(3).join("."),
              }))}
            specs={[
              { path: "label", label: "Milestone name", maxLength: 100 },
              {
                path: "percent_of_quoted_goods",
                label: "Goods value (%)",
                kind: "decimal",
              },
              {
                path: "trigger",
                label: "Trigger",
                kind: "select",
                options: [
                  "ORDER_CONFIRMATION",
                  "DISPATCH",
                  "DELIVERY",
                  "ACCEPTANCE",
                  "FIXED_DATE",
                ],
              },
              { path: "due_on", label: "Fixed due date", kind: "date" },
            ]}
          />
          <Button
            variant="ghost"
            size="icon"
            title="Remove milestone"
            aria-label={`Remove milestone ${index + 1}`}
            onClick={() =>
              change(
                setValue(
                  facts,
                  "commercial_terms.milestone_schedule",
                  items.filter((_, current) => current !== index),
                ),
              )
            }
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}
      <Button
        variant="outline"
        onClick={() =>
          change(
            setValue(facts, "commercial_terms.milestone_schedule", [
              ...items,
              {
                label: "",
                percent_of_quoted_goods: "100",
                trigger: "ORDER_CONFIRMATION",
              },
            ]),
          )
        }
      >
        <Plus className="size-4" />
        Add milestone
      </Button>
    </section>
  );
}
