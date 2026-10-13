"use client";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import { type Assignment, title } from "@/lib/operations";
import { type Values } from "@/lib/trades";
import { ConsignmentHeader, Facts, MovementTimeline, Section } from "./shared";
import { EvidenceUpload } from "./evidence-upload";
import { DriverPacket } from "@/components/compliance/driver-packet";
import type { Readiness } from "@/lib/guarded-dispatch";
import { CommittedRoute } from "@/components/freight/route-plan";

const incident: FieldSpec[] = [
  {
    path: "incident_type",
    label: "Incident",
    kind: "select",
    options: [
      "DELAY",
      "BREAKDOWN",
      "DAMAGE",
      "TEMPERATURE",
      "ROAD_OBSTRUCTION",
      "ACCIDENT",
      "OTHER",
    ],
    required: true,
  },
  {
    path: "reported_severity",
    label: "Reported severity",
    kind: "select",
    options: ["LOW", "MEDIUM", "HIGH"],
    required: true,
  },
  {
    path: "description",
    label: "Incident description",
    kind: "textarea",
    required: true,
  },
  {
    path: "observed_temperature_c",
    label: "Observed temperature (C)",
    kind: "decimal",
  },
  {
    path: "expected_delay_minutes",
    label: "Expected delay (minutes)",
    kind: "integer",
  },
];
export function DriverTask({ id }: { id: string }) {
  const { org, me } = useTradeContext();
  const resource = useOperationsResource<Assignment>(`/assignments/${id}`, org);
  const action = useOperationalMutation(org, resource.reload);
  const [kind, setKind] = useState("PICKUP_CONFIRMED");
  const [eventId, setEventId] = useState(() => crypto.randomUUID());
  const [values, setValues] = useState<Values>({
    occurred_at: new Date().toISOString(),
  });
  const [payload, setPayload] = useState<Values>({});
  const assignment = resource.data,
    cn = assignment?.consignment;
  const projections = useOperationsResource<{ items: Values[] }>(
    `/consignments/${cn?.id ?? "00000000-0000-0000-0000-000000000000"}/document-operational-projections`,
    org,
  );
  const gateAction =
    cn?.movement_status === "PICKED_UP" ? "DEPARTED" : "PICKUP_CONFIRMED";
  const gate = useOperationsResource<Readiness>(
    `/consignments/${cn?.id ?? "00000000-0000-0000-0000-000000000000"}/dispatch-readiness?action=${gateAction}`,
    org,
  );
  const [clock, setClock] = useState(Date.now());
  const reloadGate = gate.reload;
  useEffect(() => {
    const ticker = window.setInterval(() => setClock(Date.now()), 1000);
    const poll = window.setInterval(() => void reloadGate(), 5000);
    return () => {
      window.clearInterval(ticker);
      window.clearInterval(poll);
    };
  }, [reloadGate]);
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!assignment || !cn) return <p role="status">Loading driver task...</p>;
  const allowed =
    cn.allowed_actions.includes("shipment.event.record") &&
    assignment.driver_user_id === me.user.id &&
    assignment.id === cn.active_assignment_id;
  const choices = [
    ...(cn.movement_status === "NOT_STARTED" ? ["PICKUP_CONFIRMED"] : []),
    ...(cn.movement_status === "PICKED_UP" ? ["DEPARTED"] : []),
    ...(cn.movement_status === "IN_TRANSIT" ? ["ARRIVED"] : []),
    ...(cn.movement_status === "ARRIVED" ? ["DELIVERY_HANDOVER_REPORTED"] : []),
    "LOCATION_REPORTED",
    "ETA_UPDATED",
    "INCIDENT_REPORTED",
  ];
  const selected = choices.includes(kind) ? kind : choices[0];
  const needsGate = ["PICKUP_CONFIRMED", "DEPARTED"].includes(selected);
  const authorisation = gate.data?.authorisation;
  const ready =
    gate.data?.state === "READY" &&
    !!authorisation &&
    Date.parse(authorisation.expires_at) > clock &&
    Date.parse(authorisation.valid_from) <= clock;
  const fields: FieldSpec[] =
    selected === "PICKUP_CONFIRMED"
      ? [
          {
            path: "actual_gross_weight_kg",
            label: "Actual gross weight (kg)",
            kind: "decimal",
            required: true,
          },
          {
            path: "actual_package_count",
            label: "Actual package count",
            kind: "integer",
            required: true,
          },
        ]
      : selected === "ETA_UPDATED"
        ? [
            {
              path: "expected_arrival_at",
              label: "Expected arrival (IST)",
              kind: "datetime",
              required: true,
            },
            {
              path: "reason",
              label: "ETA reason",
              kind: "textarea",
              required: true,
            },
          ]
        : selected === "INCIDENT_REPORTED"
          ? incident
          : [];
  return (
    <div className="space-y-5">
      <ConsignmentHeader cn={cn} />
      <Section name="Assignment facts">
        <Facts
          values={{
            pickup: cn.pickup_address_snapshot,
            delivery: cn.delivery_address_snapshot,
            ...cn.plan_json,
          }}
        />
        {["pickup", "delivery"].map((place) => (
          <a
            key={place}
            className="mr-4 text-sm text-accent underline"
            href={`tel:${String(cn.plan_json[`${place}_contact_phone_e164`])}`}
          >
            Call {place} contact
          </a>
        ))}
        {cn.items.map((i) => (
          <Facts
            key={i.id}
            values={{
              goods: i.description_snapshot,
              quantity: `${i.allocated_quantity} ${i.uqc}`,
              cargo: i.cargo_declarations_snapshot,
            }}
          />
        ))}
      </Section>
      <CommittedRoute consignmentId={cn.id} />
      {!!projections.data?.items.length && (
        <Section name="Operational document evidence">
          {projections.data.items.map((p) => (
            <Facts
              key={String(p.document_id)}
              values={{
                document_type: p.document_type,
                execution_mode: p.execution_mode,
                printed_fields: p.fields,
                dispatch_readiness: p.dispatch_readiness,
              }}
            />
          ))}
        </Section>
      )}
      {allowed && cn.movement_status !== "DELIVERY_CLOSED" && (
        <DriverPacket readiness={gate.data} reload={gate.reload} />
      )}
      {needsGate && (
        <Section name="Platform dispatch authorisation">
          <Facts
            values={{
              readiness: gate.data?.state ?? "NOT_ASSESSED",
              blockers: gate.data?.reasons ?? [],
              authorisation_state:
                authorisation?.effective_state ?? "NOT_ISSUED",
              remaining_seconds: authorisation
                ? Math.max(
                    0,
                    Math.floor(
                      (Date.parse(authorisation.expires_at) - clock) / 1000,
                    ),
                  )
                : null,
            }}
          />
          {!ready && (
            <p className="text-sm text-amber-900">
              Contact the seller compliance preparer or carrier dispatcher for a
              current reviewed release and authorisation.
            </p>
          )}
        </Section>
      )}
      {allowed && cn.movement_status !== "DELIVERY_CLOSED" && (
        <Section name="Movement observation">
          <form
            className="space-y-4"
            onSubmit={async (e) => {
              e.preventDefault();
              let data: Values = {};
              if (selected === "PICKUP_CONFIRMED")
                data = {
                  ...payload,
                  items: cn.items.map((i) => ({
                    consignment_item_id: i.id,
                    loaded_quantity: i.allocated_quantity,
                    uqc: i.uqc,
                  })),
                };
              else if (["ETA_UPDATED", "INCIDENT_REPORTED"].includes(selected))
                data = payload;
              const result = await action.run(`/consignments/${cn.id}/events`, {
                client_event_id: eventId,
                event_type: selected,
                assignment_id: id,
                ...(needsGate
                  ? {
                      dispatch_authorization_id: authorisation?.id,
                      ...(selected === "PICKUP_CONFIRMED"
                        ? {
                            loading_manifest_revision_id:
                              authorisation?.loading_manifest_revision_id,
                          }
                        : {}),
                    }
                  : {}),
                ...values,
                payload: data,
              });
              if (result) {
                setEventId(crypto.randomUUID());
                setPayload({});
                setValues({ occurred_at: new Date().toISOString() });
                await gate.reload();
              }
            }}
          >
            <label className="text-sm font-medium">
              Event
              <select
                className="mt-1 block w-full rounded border p-2"
                value={selected}
                onChange={(e) => {
                  setKind(e.target.value);
                  setPayload({});
                  setValues({ occurred_at: new Date().toISOString() });
                  setEventId(crypto.randomUUID());
                }}
              >
                {choices.map((k) => (
                  <option key={k} value={k}>
                    {title(k)}
                  </option>
                ))}
              </select>
            </label>
            <Fields
              specs={[
                {
                  path: "occurred_at",
                  label: "Observed at (IST)",
                  kind: "datetime",
                  required: true,
                },
                ...(selected === "LOCATION_REPORTED"
                  ? [
                      {
                        path: "latitude",
                        label: "Latitude",
                        kind: "decimal" as const,
                        required: true,
                      },
                      {
                        path: "longitude",
                        label: "Longitude",
                        kind: "decimal" as const,
                        required: true,
                      },
                    ]
                  : []),
                { path: "notes", label: "Observation notes", kind: "textarea" },
              ]}
              values={values}
              onChange={setValues}
              errors={action.error?.fields}
            />
            <Fields
              specs={fields}
              values={payload}
              onChange={setPayload}
              errors={action.error?.fields}
            />
            {action.error && (
              <p role="alert" className="text-red-800">
                {action.error.code}: {action.error.message}
              </p>
            )}
            <Button disabled={action.pending || (needsGate && !ready)}>
              <Check className="size-4" />
              Record {title(selected)}
            </Button>
          </form>
        </Section>
      )}
      <Section name="Movement timeline">
        <MovementTimeline cn={cn} />
      </Section>
      <Section name="Operational evidence">
        <EvidenceUpload
          tradeId={cn.trade_id}
          consignments={[cn]}
          records={cn.documents ?? []}
          consignmentOnly
          reload={resource.reload}
        />
      </Section>
    </div>
  );
}
