"use client";
import { useState } from "react";
import Link from "next/link";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { type Assignment, type Consignment } from "@/lib/operations";
import {
  ActionForm,
  ConsignmentHeader,
  Facts,
  Section,
  reason,
} from "./shared";
import { planFields } from "./planner";

export function AssignmentDesk({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Consignment>(
    `/consignments/${id}`,
    org,
  );
  const [search, setSearch] = useState("");
  const carriers = useOperationsResource<{
    items: { organization_id: string; organization_name: string }[];
  }>(`/carriers?q=${encodeURIComponent(search)}`, org);
  const cn = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!cn) return <p role="status">Loading assignment...</p>;
  const unpicked =
    cn.movement_status === "NOT_STARTED" && cn.planning_status !== "CANCELLED";
  return (
    <div className="space-y-5">
      <ConsignmentHeader cn={cn} />
      <Section name="Cargo and timing">
        <Facts
          values={{
            pickup: cn.pickup_address_snapshot,
            delivery: cn.delivery_address_snapshot,
            ...cn.plan_json,
          }}
        />
        {cn.items.map((i) => (
          <Facts
            key={i.id}
            values={{
              goods: i.description_snapshot,
              quantity: `${i.allocated_quantity} ${i.uqc}`,
              constraints: i.cargo_declarations_snapshot,
            }}
          />
        ))}
      </Section>
      {unpicked && cn.allowed_actions.includes("consignment.plan") && (
        <Section name="Operational plan">
          <details>
            <summary className="cursor-pointer text-sm font-medium">
              Edit before pickup
            </summary>
            <ActionForm
              name="Save operational plan"
              method="PATCH"
              path={`/consignments/${id}`}
              etag={cn.etag}
              initial={cn.plan_json}
              specs={planFields}
              reload={resource.reload}
            />
          </details>
        </Section>
      )}
      {unpicked &&
        cn.allowed_actions.includes("transport.assign") &&
        cn.coordinating_organization_id === org && (
          <Section name="Propose carrier assignment">
            <label className="text-sm font-medium">
              Search carriers
              <input
                className="mt-1 block w-full rounded border p-2"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <ActionForm
              name="Propose assignment"
              path={`/consignments/${id}/assignments`}
              etag={cn.etag}
              initial={{
                booking_start_at: cn.plan_json.planned_pickup_start,
                booking_end_at: cn.plan_json.expected_delivery_at,
              }}
              specs={[
                {
                  path: "carrier_organization_id",
                  label: "Carrier",
                  kind: "select",
                  options: Object.fromEntries(
                    (carriers.data?.items ?? []).map((c) => [
                      c.organization_id,
                      c.organization_name,
                    ]),
                  ),
                  required: true,
                },
                {
                  path: "booking_start_at",
                  label: "Booking starts (IST)",
                  kind: "datetime",
                  required: true,
                },
                {
                  path: "booking_end_at",
                  label: "Booking ends (IST)",
                  kind: "datetime",
                  required: true,
                },
                { path: "vehicle_id", label: "Suggested vehicle ID" },
                { path: "driver_user_id", label: "Suggested driver ID" },
                {
                  path: "notes",
                  label: "Assignment notes",
                  kind: "textarea",
                  maxLength: 1000,
                },
              ]}
              reload={resource.reload}
            />
          </Section>
        )}
      <Section name="Transport assignments">
        {cn.assignments.map((a) => (
          <article className="space-y-4 border-b border-line py-4" key={a.id}>
            <Facts
              values={{
                assignment: a.id,
                status: a.status,
                booking_start: a.booking_start_at,
                booking_end: a.booking_end_at,
                vehicle: a.vehicle_snapshot,
                driver: a.driver_snapshot,
                ...a.suitability_json,
              }}
            />
            <p className="text-sm text-secondary">
              Operational consent only. Freight price and dispatch readiness are
              not approved.
            </p>
            {a.status === "PROPOSED" &&
              a.carrier_organization_id === org &&
              cn.allowed_actions.includes("assignment.respond") && (
                <CarrierDecision assignment={a} reload={resource.reload} />
              )}{" "}
            {a.status === "ACCEPTED" &&
              cn.allowed_actions.includes("shipment.event.record") && (
                <Link
                  className="text-accent underline"
                  href={`/shipments/tasks/${a.id}`}
                >
                  Open driver task
                </Link>
              )}
          </article>
        ))}
      </Section>
    </div>
  );
}

function CarrierDecision({
  assignment,
  reload,
}: {
  assignment: Assignment;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const vehicles = useOperationsResource<{
    items: { id: string; registration_number: string; active: boolean }[];
  }>(`/organizations/${org}/vehicles`, org);
  const drivers = useOperationsResource<{
    items: { id: string; display_name: string }[];
  }>(`/organizations/${org}/drivers`, org);
  return (
    <div className="space-y-4">
      <ActionForm
        name="Accept vehicle and driver assignment"
        path={`/assignments/${assignment.id}/decisions`}
        initial={{
          decision: "ACCEPT",
          vehicle_id: assignment.vehicle_id,
          driver_user_id: assignment.driver_user_id,
        }}
        specs={[
          {
            path: "vehicle_id",
            label: "Owned vehicle",
            kind: "select",
            options: Object.fromEntries(
              (vehicles.data?.items ?? [])
                .filter((v) => v.active)
                .map((v) => [v.id, v.registration_number]),
            ),
            required: true,
          },
          {
            path: "driver_user_id",
            label: "Active driver",
            kind: "select",
            options: Object.fromEntries(
              (drivers.data?.items ?? []).map((d) => [d.id, d.display_name]),
            ),
            required: true,
          },
        ]}
        reload={reload}
      />
      <details>
        <summary className="cursor-pointer text-sm text-red-800">
          Decline proposal
        </summary>
        <ActionForm
          name="Decline assignment"
          path={`/assignments/${assignment.id}/decisions`}
          initial={{ decision: "DECLINE" }}
          specs={reason}
          reload={reload}
        />
      </details>
    </div>
  );
}
