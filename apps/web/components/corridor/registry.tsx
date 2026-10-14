"use client";
import { useState } from "react";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import {
  ActionForm,
  Facts,
  Section,
  reason,
} from "@/components/operations/shared";
import type { CorridorRegistry } from "@/lib/corridor";
import type { FieldSpec } from "@/components/trades/fields";
import type { Values } from "@/lib/trades";
import { CorridorForm } from "./form";
import { EventDraft } from "./event-draft";

const mode: FieldSpec = {
  path: "environment",
  label: "Environment",
  kind: "select",
  options: ["SIMULATION", "PRODUCTION"],
  required: true,
};
const windowFields: FieldSpec[] = [
  {
    path: "effective_from",
    label: "Effective from",
    kind: "datetime",
    required: true,
  },
  {
    path: "effective_until",
    label: "Effective until",
    kind: "datetime",
    required: true,
  },
];

export function CorridorRegistryDesk({
  capabilities,
}: {
  capabilities: string[];
}) {
  const { org, me } = useTradeContext();
  const resource = useOperationsResource<CorridorRegistry>(
    "/corridor/registry",
    org,
  );
  const [sourceItem, setSourceItem] = useState("");
  const data = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading corridor registry...</p>;
  const prepare = capabilities.includes("regulation.source.register");
  const review = capabilities.includes("regulation.pack.review");
  const publish = capabilities.includes("regulation.pack.publish");
  const now = new Date().toISOString();
  const later = new Date(Date.now() + 86400000).toISOString();
  return (
    <Section name="Corridor source and effect registry">
      {data.source_connections.map((row) => (
        <article key={row.id} className="space-y-3 border-b py-3">
          <strong>
            {row.provider_code} / {row.environment}
          </strong>
          <Facts
            values={{
              source_connection_id: row.id,
              status: row.status,
              provenance: row.connection_json,
            }}
          />
          {prepare && (
            <ActionForm
              name="Update ingress status"
              path={`/corridor/source-connections/${row.id}/status`}
              etag={row.etag}
              reload={resource.reload}
              initial={{ status: row.status }}
              specs={[
                {
                  path: "status",
                  label: "Status",
                  kind: "select",
                  options: [
                    "CONFIGURED",
                    "DISABLED",
                    "NEEDS_REVIEW",
                    "NOT_AUTHORISED",
                  ],
                },
                ...reason,
              ]}
            />
          )}
        </article>
      ))}
      {prepare && (
        <details>
          <summary className="cursor-pointer font-medium">
            Register manual source connection
          </summary>
          <CorridorForm
            name="Register source"
            path="/corridor/source-connections"
            reload={resource.reload}
            initial={{
              provider_code: "MANUAL_OFFICIAL",
              environment: "SIMULATION",
              source_kind: "OFFICIAL_ADVISORY",
              documented_endpoint_reference:
                "Manual secured official advisory upload",
              endpoint_contract_version: "MANUAL_ADVISORY_V1",
              approved_https_hosts: [],
              covered_state_codes: [],
              state_code: "27",
              covered_event_kinds: [
                "ROAD_CLOSURE",
                "WEATHER_WARNING",
                "REOPENING_NOTICE",
              ],
              polling_interval_seconds: 300,
              maximum_item_age_seconds: 3600,
              request_timeout_seconds: 15,
              retention_policy: "PERMITTED_ARCHIVE",
              source_item_storage_allowed: true,
              export_allowed: false,
              article_storage_allowed: false,
              attribution_text: "",
            }}
            specs={[
              mode,
              {
                path: "state_code",
                label: "Covered GST state code",
                required: true,
              },
              {
                path: "documented_endpoint_reference",
                label: "Source documentation reference",
                required: true,
              },
              {
                path: "attribution_text",
                label: "Required source attribution",
                required: true,
              },
            ]}
            transform={({ state_code, ...v }) => ({
              ...v,
              covered_state_codes: [state_code],
            })}
          />
        </details>
      )}
      {prepare &&
        data.source_connections.some((c) => c.status === "CONFIGURED") && (
          <details>
            <summary className="cursor-pointer font-medium">
              Retain secured source item
            </summary>
            <CorridorForm
              name="Retain source"
              path="/corridor/manual-source-items"
              reload={resource.reload}
              saved={(v) => setSourceItem(String(v.id))}
              initial={{
                source_connection_id: data.source_connections.find(
                  (c) => c.status === "CONFIGURED",
                )?.id,
                provider_item_key: "",
                artifact_attachment_id: null,
                source_issued_at: now,
                retrieved_at: now,
                source_reference: "",
                payload_sha256: "",
                mime_type: "application/pdf",
                language: "en",
                limitations: [],
              }}
              specs={[
                {
                  path: "source_connection_id",
                  label: "Source connection",
                  kind: "select",
                  options: Object.fromEntries(
                    data.source_connections
                      .filter((c) => c.status === "CONFIGURED")
                      .map((c) => [
                        c.id,
                        `${c.provider_code} / ${c.environment}`,
                      ]),
                  ),
                },
                {
                  path: "provider_item_key",
                  label: "Publisher item identifier",
                  required: true,
                },
                {
                  path: "artifact_attachment_id",
                  label: "Dedicated secured attachment ID",
                },
                {
                  path: "payload_sha256",
                  label: "Exact source SHA-256",
                  required: true,
                },
                {
                  path: "source_reference",
                  label: "Publisher reference",
                  required: true,
                },
                {
                  path: "source_issued_at",
                  label: "Publisher issued at",
                  kind: "datetime",
                },
                {
                  path: "retrieved_at",
                  label: "Retrieved at",
                  kind: "datetime",
                  required: true,
                },
              ]}
            />
            {sourceItem && (
              <p className="break-words text-sm">
                Retained source item: {sourceItem}
              </p>
            )}
          </details>
        )}
      {prepare && (
        <details>
          <summary className="cursor-pointer font-medium">
            Create incident
          </summary>
          <ActionForm
            name="Create incident"
            path="/corridor/incidents"
            reload={resource.reload}
            initial={{
              environment: "SIMULATION",
              visibility: "ORG_ONLY",
              consignment_id: null,
            }}
            specs={[
              mode,
              {
                path: "visibility",
                label: "Visibility",
                kind: "select",
                options: [
                  "ORG_ONLY",
                  "PUBLIC_APPROVED",
                  "CONSIGNMENT_ONLY",
                  "RESTRICTED",
                ],
              },
              { path: "consignment_id", label: "Consignment ID (when scoped)" },
            ]}
          />
        </details>
      )}
      {data.incidents.map((incident) => (
        <article key={incident.id} className="space-y-4 border-t py-4">
          <h4 className="break-words font-semibold">
            Incident {incident.id} / {incident.environment}
          </h4>
          {prepare && (
            <EventDraft
              incident={incident}
              sourceItem={sourceItem}
              reload={resource.reload}
            />
          )}
          {incident.revisions.map((row) => (
            <div className="space-y-3 border-l pl-3" key={row.id}>
              <strong>
                {String(row.event_json.headline)} / {row.state}
              </strong>
              <details>
                <summary className="cursor-pointer text-sm font-medium">
                  Exact event and provenance
                </summary>
                <Facts
                  values={{
                    event: row.event_json,
                    hash: row.content_hash,
                    history: row.actions,
                  }}
                />
              </details>
              {review &&
                row.created_by_user_id !== me?.user.id &&
                row.state === "PENDING_REVIEW" && (
                  <ActionForm
                    name="Review event"
                    path={`/corridor/event-revisions/${row.id}/reviews`}
                    reload={resource.reload}
                    initial={{
                      content_hash: row.content_hash,
                      decision: "APPROVE",
                    }}
                    specs={[
                      {
                        path: "decision",
                        label: "Decision",
                        kind: "select",
                        options: ["APPROVE", "RETURN"],
                      },
                      ...reason,
                    ]}
                  />
                )}
              {publish &&
                row.created_by_user_id !== me?.user.id &&
                row.actions.at(-1)?.action === "APPROVED" && (
                  <ActionForm
                    name="Publish reviewed event"
                    path={`/corridor/event-revisions/${row.id}/publications`}
                    reload={resource.reload}
                    initial={{ content_hash: row.content_hash }}
                    specs={reason}
                  />
                )}
            </div>
          ))}
        </article>
      ))}
      {capabilities.includes("regulation.pack.prepare") && (
        <details>
          <summary className="cursor-pointer font-medium">
            Prepare operational effect policy
          </summary>
          <CorridorForm
            name="Prepare application policy"
            path="/corridor/effect-policy-revisions"
            reload={resource.reload}
            initial={{
              environment: "SIMULATION",
              policy_code: "",
              policy_class: "APPLICATION_POLICY",
              event_kind: "ROAD_CLOSURE",
              state_code: "27",
              source_kind: "OFFICIAL_ADVISORY",
              effect: "REQUIRE_REVIEW",
              minimum_precision: "ADMIN_AREA",
              vehicle_profile_codes: [],
              cargo_profile_codes: [],
              maximum_source_age_seconds: 3600,
              missing_coverage_action: "SHOW_LIMITATION",
              required_source_kinds: [],
              delay_basis: "NONE",
              minimum_delay_seconds: null,
              maximum_delay_seconds: null,
              release_condition: "REOPENING_EVIDENCE",
              reference: "",
              limitations: [],
              effective_from: now,
              effective_until: later,
            }}
            specs={[
              mode,
              { path: "policy_code", label: "Policy code", required: true },
              {
                path: "event_kind",
                label: "Event kind",
                kind: "select",
                options: [
                  "ROAD_CLOSURE",
                  "WEATHER_WARNING",
                  "TRAFFIC_RESTRICTION",
                  "CONGESTION_REPORT",
                ],
              },
              { path: "state_code", label: "GST state scope", required: true },
              {
                path: "source_kind",
                label: "Source kind",
                kind: "select",
                options: [
                  "OFFICIAL_ADVISORY",
                  "OFFICIAL_CAP",
                  "OFFICIAL_WEATHER_API",
                ],
              },
              {
                path: "effect",
                label: "Operational effect",
                kind: "select",
                options: ["REQUIRE_REVIEW", "ADVISORY_ONLY", "EXCLUDE_EDGE"],
              },
              {
                path: "minimum_precision",
                label: "Minimum geography precision",
                kind: "select",
                options: [
                  "EXACT_EDGE",
                  "SOURCE_POLYGON",
                  "ADMIN_AREA",
                  "APPROXIMATE",
                ],
              },
              {
                path: "reference",
                label: "Policy justification reference",
                required: true,
              },
              ...windowFields,
            ]}
            transform={({
              event_kind,
              state_code,
              source_kind,
              reference,
              ...v
            }: Values) => ({
              ...v,
              event_kinds: [event_kind],
              state_codes: [state_code],
              source_kinds: [source_kind],
              source_references: [reference],
            })}
          />
        </details>
      )}
      {data.policies.map((row) => (
        <article key={row.id} className="space-y-3 border-t py-3">
          <strong>
            {row.policy_code} / {row.active ? "Active" : "Not active"}
          </strong>
          <details>
            <summary className="cursor-pointer font-medium">
              Policy and review history
            </summary>
            <Facts
              values={{
                policy: row.policy_json,
                content_hash: row.content_hash,
                actions: row.actions,
              }}
            />
          </details>
          {review &&
            row.created_by_user_id !== me?.user.id &&
            !row.active &&
            row.actions.at(-1)?.action !== "PUBLISHED" && (
              <ActionForm
                name="Review application policy"
                path={`/corridor/effect-policy-revisions/${row.id}/review-approvals`}
                reload={resource.reload}
                initial={{
                  content_hash: row.content_hash,
                  decision: "APPROVE",
                }}
                specs={[
                  {
                    path: "decision",
                    label: "Decision",
                    kind: "select",
                    options: ["APPROVE", "RETURN"],
                  },
                  ...reason,
                ]}
              />
            )}
          {publish &&
            row.created_by_user_id !== me?.user.id &&
            row.actions.at(-1)?.action === "APPROVED" && (
              <ActionForm
                name="Publish application policy"
                path={`/corridor/effect-policy-revisions/${row.id}/publications`}
                reload={resource.reload}
                initial={{ content_hash: row.content_hash }}
                specs={reason}
              />
            )}
        </article>
      ))}
    </Section>
  );
}
