"use client";
import Link from "next/link";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { type Assignment } from "@/lib/operations";
import { ActionForm, Facts, Mode, Refresh, Section } from "./shared";

export function TransportTasks() {
  const { org, me } = useTradeContext();
  const resource = useOperationsResource<{ items: Assignment[] }>(
    "/me/transport-tasks",
    org,
  );
  const member = me.memberships.find((m) => m.organization_id === org);
  const manage = member?.permissions.some(
    (p) => p.permission_code === "vehicle.manage",
  );
  return (
    <div className="space-y-5">
      <header className="flex justify-between gap-3">
        <h2 className="text-xl font-semibold">Transport tasks</h2>
        <Refresh reload={resource.reload} />
      </header>
      {resource.error && <p role="alert">{resource.error}</p>}
      {member?.permissions.some(
        (p) => p.permission_code === "freight.rfq.invited.read",
      ) && (
        <Link href="/optimizer/freight" className="text-accent underline">
          Invited freight RFQs and route offers
        </Link>
      )}
      {resource.data?.items.map((a) => (
        <article key={a.id} className="space-y-3 border-b py-4">
          <div className="flex flex-wrap justify-between gap-3">
            <strong>{a.consignment?.reference}</strong>
            <Mode mode={a.execution_mode} />
          </div>
          <Facts
            values={{
              assignment_status: a.status,
              movement: a.consignment?.movement_status,
              booking_start: a.booking_start_at,
              booking_end: a.booking_end_at,
            }}
          />
          <Link
            className="mr-4 text-accent underline"
            href={`/shipments/consignments/${a.consignment_id}/assignment`}
          >
            Assignment
          </Link>
          {a.driver_user_id === me.user.id && a.status === "ACCEPTED" && (
            <Link
              className="text-accent underline"
              href={`/shipments/tasks/${a.id}`}
            >
              Open driver task
            </Link>
          )}
        </article>
      ))}
      {resource.data && !resource.data.items.length && (
        <p>No accessible transport tasks.</p>
      )}
      {manage && <CarrierInventory />}
    </div>
  );
}
function CarrierInventory() {
  const { org } = useTradeContext();
  const profile = useOperationsResource<{
    etag: string;
    profile_json: Record<string, unknown>;
  } | null>(`/organizations/${org}/carrier-profile`, org);
  const vehicles = useOperationsResource<{
    items: {
      id: string;
      etag: string;
      vehicle_json: Record<string, unknown>;
      registration_number: string;
    }[];
  }>(`/organizations/${org}/vehicles`, org);
  const specs = [
    {
      path: "registration_number",
      label: "Registration number",
      required: true,
    },
    {
      path: "vehicle_type",
      label: "Vehicle type",
      kind: "select" as const,
      options: [
        "VAN",
        "LIGHT_TRUCK",
        "MEDIUM_TRUCK",
        "HEAVY_TRUCK",
        "TRAILER",
        "REFRIGERATED_TRUCK",
        "OTHER",
      ],
      required: true,
    },
    {
      path: "declared_payload_capacity_kg",
      label: "Declared payload capacity (kg)",
      kind: "decimal" as const,
      required: true,
    },
    {
      path: "declared_volume_capacity_m3",
      label: "Declared volume capacity (m3)",
      kind: "decimal" as const,
    },
    { path: "refrigerated", label: "Refrigerated", kind: "boolean" as const },
    {
      path: "temperature_min_c",
      label: "Temperature minimum (C)",
      kind: "decimal" as const,
    },
    {
      path: "temperature_max_c",
      label: "Temperature maximum (C)",
      kind: "decimal" as const,
    },
    {
      path: "declared_hazardous_capable",
      label: "Declared hazardous capability",
      kind: "boolean" as const,
    },
    { path: "active", label: "Active", kind: "boolean" as const },
  ];
  return (
    <>
      <Section name="Self-declared carrier profile">
        <ActionForm
          key={org + String(profile.data?.etag)}
          name="Save carrier declaration"
          method="PUT"
          path={`/organizations/${org}/carrier-profile`}
          initial={
            profile.data?.profile_json ?? {
              directory_visibility: "TRADING_PROFILE",
              active: true,
            }
          }
          etag={profile.data?.etag}
          specs={[
            {
              path: "dispatch_contact_name",
              label: "Dispatch contact",
              required: true,
            },
            {
              path: "dispatch_contact_phone_e164",
              label: "Dispatch phone",
              kind: "phone",
              required: true,
            },
            {
              path: "dispatch_contact_email",
              label: "Dispatch email",
              kind: "email",
            },
            {
              path: "transporter_identifier_declared",
              label: "Declared transporter identifier",
            },
            { path: "gst_registration_id", label: "Owned registration ID" },
            {
              path: "directory_visibility",
              label: "Directory visibility",
              kind: "select",
              options: ["PRIVATE", "TRADING_PROFILE"],
            },
            { path: "active", label: "Carrier active", kind: "boolean" },
          ]}
          reload={profile.reload}
        />
      </Section>
      <Section name="Vehicle inventory">
        <ActionForm
          name="Add declared vehicle"
          path={`/organizations/${org}/vehicles`}
          initial={{
            refrigerated: false,
            active: true,
            declared_hazardous_capable: false,
          }}
          specs={specs}
          reload={vehicles.reload}
        />
        {vehicles.data?.items.map((v) => (
          <details className="mt-4 border-t py-3" key={v.id}>
            <summary className="cursor-pointer font-medium">
              {v.registration_number}
            </summary>
            <ActionForm
              name="Update vehicle declaration"
              method="PATCH"
              path={`/vehicles/${v.id}`}
              initial={v.vehicle_json}
              specs={specs}
              etag={v.etag}
              reload={vehicles.reload}
            />
          </details>
        ))}
      </Section>
    </>
  );
}
