"use client";
import { useState } from "react";
import { Play, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import { type FreightContext } from "@/lib/freight";
import { type Values } from "@/lib/trades";
import { ActionForm, Section } from "@/components/operations/shared";
import { RouteGeneration } from "./generation";

const objectives = [
  "LOWEST_COMPARABLE_COST",
  "EARLIEST_ESTIMATED_ARRIVAL",
  "BALANCED",
];
export function FreightPlanning({
  context: data,
  reload,
}: {
  context: FreightContext;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const routes = useOperationsResource<{
    items: { id: string; template_json: { state_sequence: string[] } }[];
  }>(`/consignments/${data.consignment_id}/route-templates`, org);
  const carriers = useOperationsResource<{
    items: { organization_id: string; organization_name: string }[];
  }>("/carriers", org);
  const [invited, setInvited] = useState<string[]>([]);
  const [routeIds, setRouteIds] = useState<string[]>([]);
  const [rfqValues, setRFQ] = useState<Values>({
    service_requirement_codes: ["TOLL", "FUEL_SURCHARGE", "LOADING"],
  });
  const [runValues, setRun] = useState<Values>({
    objective: "LOWEST_COMPARABLE_COST",
    balanced_weights: { cost_basis_points: 5000, time_basis_points: 5000 },
    comparison_policy: "QUOTED_AMOUNTS_ONLY",
    planning_intent: { planned_stop_seconds: 1800 },
    scenarios: [],
  });
  const [quotes, setQuotes] = useState<string[]>([]);
  const [generationId, setGenerationId] = useState("");
  const mutation = useOperationalMutation(org, reload);
  const caps = data.capabilities;
  const availableQuotes = data.rfqs.flatMap((r) =>
    r.quotes.filter((q) => q.lifecycle === "SUBMITTED"),
  );
  const toggle = (values: string[], id: string) =>
    values.includes(id) ? values.filter((v) => v !== id) : [...values, id];
  return (
    <div className="min-w-0 space-y-4">
      {caps.includes("tradetwin.plan.prepare") && (
        <Section name="Confirmed routing gates">
          {(["PICKUP", "DROP"] as const).map((role) => (
            <details key={role} className="border-b py-3">
              <summary className="cursor-pointer font-medium">
                {role === "PICKUP" ? "Pickup" : "Drop"} pin /{" "}
                {(data.locations.find((l) => l.address_role === role)
                  ?.location_json.precision as string) ?? "Unconfirmed"}
              </summary>
              <ActionForm
                name={`Confirm ${role.toLowerCase()} gate`}
                path={`/consignments/${data.consignment_id}/routing-location-revisions`}
                etag={data.consignment_etag}
                initial={{
                  address_role: role,
                  accepted_address_hash:
                    role === "PICKUP"
                      ? data.pickup_address_hash
                      : data.drop_address_hash,
                  state_code:
                    role === "PICKUP"
                      ? data.inherited.origin_state_code
                      : data.inherited.destination_state_code,
                  position_source:
                    data.execution_mode === "SIMULATION"
                      ? "SIMULATION"
                      : "USER_PIN",
                  precision: "CONFIRMED_LOADING_GATE",
                  state_coordinate_conflict_resolved: false,
                }}
                specs={[
                  {
                    path: "latitude",
                    label: "Latitude",
                    kind: "decimal",
                    required: true,
                  },
                  {
                    path: "longitude",
                    label: "Longitude",
                    kind: "decimal",
                    required: true,
                  },
                  {
                    path: "precision",
                    label: "Pin precision",
                    kind: "select",
                    options: [
                      "CONFIRMED_LOADING_GATE",
                      "PREMISES",
                      "AREA_CENTROID",
                      "UNKNOWN",
                    ],
                  },
                  {
                    path: "state_coordinate_conflict_resolved",
                    label: "Gate and declared state confirmed",
                    kind: "boolean",
                  },
                  {
                    path: "note",
                    label: "Confirmation basis",
                    kind: "textarea",
                  },
                ]}
                reload={reload}
              />
            </details>
          ))}
          <details className="border-b py-3">
            <summary className="cursor-pointer font-medium">
              Generate retained road alternatives
            </summary>
            <ActionForm
              name="Generate route templates"
              path={`/consignments/${data.consignment_id}/route-generation-jobs`}
              initial={{
                pickup_location_revision_id: data.pickup_location_revision_id,
                drop_location_revision_id: data.drop_location_revision_id,
                maximum_alternatives: 3,
                objective: "TIME",
              }}
              specs={[
                {
                  path: "vehicle_profile_revision_id",
                  label: "Nominated routing-profile revision",
                  required: true,
                },
                {
                  path: "dataset_revision_id_or_provider_connection_id",
                  label: "Reviewed retained dataset",
                  kind: "select",
                  options: Object.fromEntries(
                    data.datasets.map((d) => [
                      d.id,
                      `${d.dataset_code} / ${d.version}`,
                    ]),
                  ),
                },
                {
                  path: "departure_at",
                  label: "Departure (IST)",
                  kind: "datetime",
                  required: true,
                },
                {
                  path: "objective",
                  label: "Route generation objective",
                  kind: "select",
                  options: ["DISTANCE", "TIME"],
                },
              ]}
              reload={async () => {
                await routes.reload();
                await reload();
              }}
              onSaved={(result) =>
                setGenerationId((result as { job_id: string }).job_id)
              }
            />
            {generationId && (
              <RouteGeneration id={generationId} reload={routes.reload} />
            )}
          </details>
        </Section>
      )}
      {caps.includes("freight.rfq.prepare") && (
        <Section name="Route-specific freight request">
          <form
            className="space-y-4"
            onSubmit={async (e) => {
              e.preventDefault();
              await mutation.run(
                `/consignments/${data.consignment_id}/freight-rfqs`,
                {
                  ...rfqValues,
                  pickup_location_revision_id: data.pickup_location_revision_id,
                  drop_location_revision_id: data.drop_location_revision_id,
                  requested_route_template_revision_ids: routeIds,
                  invited_carrier_organisation_ids: invited,
                },
                data.consignment_etag,
              );
            }}
          >
            <fieldset className="space-y-2">
              <legend className="mb-2 font-medium">Route templates</legend>
              {routes.data?.items.map((r) => (
                <label key={r.id} className="flex gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={routeIds.includes(r.id)}
                    onChange={() => setRouteIds(toggle(routeIds, r.id))}
                  />
                  {r.template_json.state_sequence?.join(" > ") ??
                    "Unassessed corridor"}{" "}
                  / {r.id.slice(0, 8)}
                </label>
              ))}
            </fieldset>
            <fieldset className="space-y-2">
              <legend className="mb-2 font-medium">Invited carriers</legend>
              {carriers.data?.items.map((c) => (
                <label key={c.organization_id} className="flex gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={invited.includes(c.organization_id)}
                    onChange={() =>
                      setInvited(toggle(invited, c.organization_id))
                    }
                  />
                  {c.organization_name}
                </label>
              ))}
            </fieldset>
            <Fields
              specs={[
                {
                  path: "requested_pickup_window_start",
                  label: "Pickup window starts (IST)",
                  kind: "datetime",
                  required: true,
                },
                {
                  path: "requested_pickup_window_end",
                  label: "Pickup window ends (IST)",
                  kind: "datetime",
                  required: true,
                },
                {
                  path: "required_arrival_by",
                  label: "Required arrival (IST)",
                  kind: "datetime",
                },
                {
                  path: "response_deadline",
                  label: "Carrier response deadline (IST)",
                  kind: "datetime",
                  required: true,
                },
                {
                  path: "request_note",
                  label: "Operational request note",
                  kind: "textarea",
                },
              ]}
              values={rfqValues}
              onChange={setRFQ}
              errors={mutation.error?.fields}
            />
            <Button
              disabled={mutation.pending || !invited.length || !routeIds.length}
            >
              <Send className="size-4" />
              Prepare RFQ
            </Button>
          </form>
        </Section>
      )}
      {data.rfqs.map((r) => (
        <details key={r.id} className="border-b py-3">
          <summary className="cursor-pointer font-medium">
            RFQ {r.id.slice(0, 8)} / {r.lifecycle} / {r.freshness}
          </summary>
          <p className="my-3 break-all text-xs">
            Request hash: {r.request_hash}
          </p>
          {r.lifecycle === "DRAFT" && caps.includes("freight.rfq.publish") && (
            <ActionForm
              name="Publish immutable RFQ"
              path={`/freight-rfqs/${r.id}/publications`}
              etag={r.etag}
              initial={{ request_hash: r.request_hash }}
              reload={reload}
            />
          )}
          <p className="text-sm">{r.quotes.length} current carrier offers</p>
        </details>
      ))}
      {caps.includes("tradetwin.run") && (
        <Section name="Baseline inputs">
          <form
            className="space-y-4"
            onSubmit={async (e) => {
              e.preventDefault();
              await mutation.run(
                `/consignments/${data.consignment_id}/tradetwin-runs`,
                {
                  ...runValues,
                  expected_context_version: data.compliance_context_version,
                  quote_revision_ids: quotes,
                  route_template_revision_ids: [
                    ...new Set(
                      availableQuotes
                        .filter((q) => quotes.includes(q.id))
                        .map((q) => q.route_template_revision_id),
                    ),
                  ],
                },
                data.context_etag,
              );
            }}
          >
            <fieldset className="space-y-2">
              <legend className="mb-2 font-medium">Submitted offers</legend>
              {availableQuotes.map((q) => (
                <label key={q.id} className="flex gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={quotes.includes(q.id)}
                    onChange={() => setQuotes(toggle(quotes, q.id))}
                  />
                  {q.id.slice(0, 8)} / {q.effective_expiration}
                </label>
              ))}
            </fieldset>
            <Fields
              specs={runSpecs}
              values={runValues}
              onChange={setRun}
              errors={mutation.error?.fields}
            />
            <Button disabled={mutation.pending || !quotes.length}>
              <Play className="size-4" />
              Run TradeTwin
            </Button>
          </form>
        </Section>
      )}
      {mutation.error && (
        <p role="alert">
          {mutation.error.code}: {mutation.error.message}
        </p>
      )}
      {mutation.saved && <p role="status">{mutation.saved}</p>}
    </div>
  );
}
const runSpecs: FieldSpec[] = [
  {
    path: "planning_intent.intended_pickup_at",
    label: "Intended pickup (IST)",
    kind: "datetime",
    required: true,
  },
  {
    path: "planning_intent.intended_departure_at",
    label: "Intended departure (IST)",
    kind: "datetime",
    required: true,
  },
  {
    path: "planning_intent.required_arrival_by",
    label: "Required arrival (IST)",
    kind: "datetime",
  },
  {
    path: "planning_intent.planned_stop_seconds",
    label: "Planned stops (seconds)",
    kind: "integer",
  },
  {
    path: "objective",
    label: "Objective",
    kind: "select",
    options: objectives,
  },
  {
    path: "comparison_policy",
    label: "Comparison policy",
    kind: "select",
    options: ["QUOTED_AMOUNTS_ONLY", "ALLOW_DECLARED_ESTIMATES"],
  },
  {
    path: "balanced_weights.cost_basis_points",
    label: "Balanced cost weight (basis points)",
    kind: "integer",
  },
  {
    path: "balanced_weights.time_basis_points",
    label: "Balanced time weight (basis points)",
    kind: "integer",
  },
  {
    path: "cost_assumption_revision_id",
    label: "Reviewed cost-assumption revision",
  },
];
