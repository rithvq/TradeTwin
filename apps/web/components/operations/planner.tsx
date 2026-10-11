"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import { type Consignment, type Operations } from "@/lib/operations";
import { type Trade, type Values } from "@/lib/trades";
import { Facts, Mode, Section } from "./shared";

export const planFields: FieldSpec[] = [
  {
    path: "planned_pickup_start",
    label: "Pickup window start (IST)",
    kind: "datetime",
    required: true,
  },
  {
    path: "planned_pickup_end",
    label: "Pickup window end (IST)",
    kind: "datetime",
    required: true,
  },
  {
    path: "expected_delivery_at",
    label: "Expected delivery (IST)",
    kind: "datetime",
    required: true,
  },
  {
    path: "pickup_contact_name",
    label: "Pickup contact",
    required: true,
    maxLength: 100,
  },
  {
    path: "pickup_contact_phone_e164",
    label: "Pickup phone",
    kind: "phone",
    required: true,
  },
  {
    path: "delivery_contact_name",
    label: "Delivery contact",
    required: true,
    maxLength: 100,
  },
  {
    path: "delivery_contact_phone_e164",
    label: "Delivery phone",
    kind: "phone",
    required: true,
  },
  {
    path: "declared_gross_weight_kg",
    label: "Gross weight (kg)",
    kind: "decimal",
    required: true,
  },
  { path: "declared_net_weight_kg", label: "Net weight (kg)", kind: "decimal" },
  { path: "declared_volume_m3", label: "Volume (m3)", kind: "decimal" },
  {
    path: "package_type",
    label: "Package type",
    kind: "select",
    options: ["CARTON", "BAG", "PALLET", "CRATE", "DRUM", "BULK", "OTHER"],
    required: true,
  },
  {
    path: "package_count",
    label: "Package count",
    kind: "integer",
    required: true,
  },
  {
    path: "packaging_notes",
    label: "Packaging notes",
    kind: "textarea",
    maxLength: 1000,
  },
  {
    path: "loading_notes",
    label: "Loading notes",
    kind: "textarea",
    maxLength: 1000,
  },
  { path: "delivery_notes", label: "Delivery notes", kind: "textarea" },
];
export function ConsignmentPlanner({ tradeId }: { tradeId: string }) {
  const { org } = useTradeContext();
  const router = useRouter();
  const trade = useOperationsResource<Trade>(`/trades/${tradeId}`, org);
  const ops = useOperationsResource<Operations>(
    `/trades/${tradeId}/operations`,
    org,
  );
  const action = useOperationalMutation(org, ops.reload);
  const [values, setValues] = useState<Values | null>(null);
  const [requested, setRequested] = useState<Record<string, string>>({});
  const revision = trade.data?.accepted_revision;
  useEffect(() => {
    setValues(null);
    setRequested({});
  }, [org, tradeId]);
  useEffect(() => {
    if (!revision || values) return;
    const delivery = revision.facts.delivery_requirements as Values;
    const pickup = revision.facts.dispatch_from as Values;
    const destination = revision.facts.ship_to as Values;
    setValues({
      source_accepted_revision_id: revision.id,
      coordinating_organization_id: revision.facts.seller_organization_id,
      planned_pickup_start: delivery.pickup_earliest_at,
      planned_pickup_end: delivery.pickup_latest_at,
      expected_delivery_at: delivery.delivery_deadline_at,
      pickup_contact_name: pickup.contact_name ?? "",
      pickup_contact_phone_e164: pickup.contact_phone_e164 ?? "",
      delivery_contact_name: destination.contact_name ?? "",
      delivery_contact_phone_e164: destination.contact_phone_e164 ?? "",
      package_type: "CARTON",
      package_count: 1,
    });
  }, [revision, values]);
  if (trade.error || ops.error)
    return <p role="alert">{trade.error || ops.error}</p>;
  if (!revision || !values || !ops.data)
    return (
      <p role="status">An accepted agreement is required for allocation.</p>
    );
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap justify-between gap-3">
        <h2 className="text-xl font-semibold">Allocate consignment</h2>
        <Mode mode={ops.data.execution_mode} />
      </header>
      <Facts
        values={{
          accepted_revision: revision.id,
          dispatch_address: revision.facts.dispatch_from,
          delivery_address: revision.facts.ship_to,
        }}
      />
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const goods = (revision.facts.items as Values[])
            .filter(
              (i) =>
                requested[String(i.line_ref)] &&
                requested[String(i.line_ref)] !== "0",
            )
            .map((i) => ({
              line_ref: i.line_ref,
              allocated_quantity: requested[String(i.line_ref)],
              uqc: i.uqc,
            }));
          const saved = await action.run<Consignment>(
            `/trades/${tradeId}/consignments`,
            { ...values, items: goods },
          );
          if (saved) router.push(`/shipments/trades/${tradeId}/operations`);
        }}
      >
        <Section name="Order allocation">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  {[
                    "Goods",
                    "Ordered",
                    "Reserved",
                    "Available",
                    "Requested",
                  ].map((t) => (
                    <th key={t} className="p-2">
                      {t}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ops.data.availability.map((line, index) => (
                  <tr key={line.line_ref}>
                    <td className="p-2">
                      {line.description} ({line.uqc})
                    </td>
                    <td className="p-2">{line.ordered_quantity}</td>
                    <td className="p-2">{line.reserved_quantity}</td>
                    <td className="p-2">{line.available_quantity}</td>
                    <td className="p-2">
                      <input
                        aria-label={`Allocate ${line.description}`}
                        className="w-32 rounded border p-2"
                        inputMode="decimal"
                        value={requested[line.line_ref] ?? ""}
                        onChange={(e) =>
                          setRequested({
                            ...requested,
                            [line.line_ref]: e.target.value,
                          })
                        }
                      />
                      {action.error?.fields
                        .filter((f) => f.path.startsWith(`items.${index}`))
                        .map((f) => (
                          <p key={f.path} className="text-xs text-red-800">
                            {f.message}
                          </p>
                        ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
        <Section name="Operational plan">
          <Fields
            specs={[
              {
                path: "coordinating_organization_id",
                label: "Coordinating organisation",
                kind: "select",
                options: {
                  [String(revision.facts.seller_organization_id)]: "Seller",
                  [String(revision.facts.buyer_organization_id)]: "Buyer",
                },
              },
              ...planFields,
            ]}
            values={values}
            onChange={setValues}
            errors={action.error?.fields}
          />
        </Section>
        {action.error && (
          <p role="alert" className="mb-3 text-red-800">
            {action.error.code}: {action.error.message}
          </p>
        )}
        <Button
          disabled={
            action.pending ||
            !ops.data.allowed_actions.includes("consignment.plan")
          }
        >
          <Save className="size-4" />
          Save draft reservation
        </Button>
      </form>
    </div>
  );
}
