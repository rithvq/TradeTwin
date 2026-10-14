"use client";
import type { CorridorRegistry } from "@/lib/corridor";
import { CorridorForm } from "./form";

export function EventDraft({
  incident,
  sourceItem,
  reload,
}: {
  incident: CorridorRegistry["incidents"][number];
  sourceItem: string;
  reload: () => Promise<void>;
}) {
  const now = new Date().toISOString();
  return (
    <details>
      <summary className="cursor-pointer font-medium">
        Draft event interpretation
      </summary>
      <CorridorForm
        name="Retain event draft"
        path={`/corridor/incidents/${incident.id}/event-revisions`}
        etag={incident.etag}
        reload={reload}
        initial={{
          source_item_id: sourceItem,
          event_kind: "ROAD_CLOSURE",
          headline: "",
          summary: "",
          source_sender: "",
          source_identifier: "",
          source_sent_at: now,
          source_message_type: "NON_CAP",
          source_status: "NON_CAP",
          upstream_references: [],
          severity: "UNKNOWN",
          assessed_effective_from: now,
          assessed_effective_until: new Date(
            Date.now() + 3600000,
          ).toISOString(),
          operational_review_due_at: new Date(
            Date.now() + 1800000,
          ).toISOString(),
          time_interpretation:
            "Reviewed source timestamps with explicit timezone",
          geometry_kind: "STATE",
          state_code: "27",
          dataset_revision_id: null,
          edge_keys_text: "",
          direction: "UNKNOWN",
          vehicle_profile_codes: [],
          cargo_profile_codes: [],
          report_basis: "PRIMARY_SOURCE_OBSERVED",
          limitations: [],
        }}
        specs={[
          {
            path: "source_item_id",
            label: "Retained source item ID",
            required: true,
          },
          {
            path: "event_kind",
            label: "Event kind",
            kind: "select",
            options: [
              "ROAD_CLOSURE",
              "TRAFFIC_RESTRICTION",
              "WEATHER_WARNING",
              "CONGESTION_REPORT",
              "FLOOD_REPORT",
              "REOPENING_NOTICE",
              "OTHER",
            ],
          },
          { path: "headline", label: "Headline", required: true },
          {
            path: "summary",
            label: "Source-backed summary",
            kind: "textarea",
            required: true,
          },
          { path: "source_sender", label: "Publisher sender", required: true },
          {
            path: "source_identifier",
            label: "Publisher message identifier",
            required: true,
          },
          {
            path: "source_sent_at",
            label: "Publisher sent at",
            kind: "datetime",
            required: true,
          },
          {
            path: "assessed_effective_from",
            label: "Assessed effect from",
            kind: "datetime",
            required: true,
          },
          {
            path: "assessed_effective_until",
            label: "Assessed effect until",
            kind: "datetime",
            required: true,
          },
          {
            path: "operational_review_due_at",
            label: "Operational review due",
            kind: "datetime",
            required: true,
          },
          { path: "severity", label: "Publisher severity", required: true },
          {
            path: "geometry_kind",
            label: "Geography",
            kind: "select",
            options: ["STATE", "ROAD_EDGE_SET"],
          },
          { path: "state_code", label: "GST state code", required: true },
          {
            path: "dataset_revision_id",
            label: "Retained road dataset ID (exact edges)",
          },
          { path: "edge_keys_text", label: "Exact edge keys, comma separated" },
          {
            path: "direction",
            label: "Direction",
            kind: "select",
            options: ["BOTH", "FORWARD", "REVERSE", "UNKNOWN"],
          },
          {
            path: "report_basis",
            label: "Report basis",
            kind: "select",
            options: [
              "PRIMARY_SOURCE_OBSERVED",
              "CORROBORATED_REPORT",
              "SINGLE_REPORT",
              "SIMULATION",
            ],
          },
        ]}
        transform={({
          geometry_kind,
          state_code,
          dataset_revision_id,
          edge_keys_text,
          direction,
          ...value
        }) => ({
          ...value,
          geography: {
            geometry_kind,
            state_codes: [state_code],
            dataset_revision_id:
              geometry_kind === "ROAD_EDGE_SET" ? dataset_revision_id : null,
            edge_keys:
              geometry_kind === "ROAD_EDGE_SET"
                ? String(edge_keys_text)
                    .split(",")
                    .map((e) => e.trim())
                    .filter(Boolean)
                : [],
            district_codes: [],
            geojson: null,
            direction,
            precision:
              geometry_kind === "ROAD_EDGE_SET" ? "EXACT_EDGE" : "ADMIN_AREA",
            basis: "REVIEWED_MAPPING",
          },
        })}
      />
    </details>
  );
}
