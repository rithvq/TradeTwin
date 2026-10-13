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
import { type FreightRFQ, type FreightSelection } from "@/lib/freight";
import { type FieldSpec } from "@/components/trades/fields";
import { type Values } from "@/lib/trades";
import { FreightCancellation } from "./cancellation";
import { QuoteEditor } from "./quote-editor";

type Fleet = {
  transport_evidence: {
    id: string;
    consignment_id: string;
    subject_id: string;
    evidence_type: string;
  }[];
  vehicles: {
    id: string;
    etag: string;
    registration_number: string;
    current_routing_profile_revision_id: string | null;
  }[];
  drivers: { id: string; display_name: string }[];
};
export function FreightCarrierDesk() {
  const { org } = useTradeContext();
  const resource = useOperationsResource<{ items: FreightRFQ[] }>(
    "/freight-rfqs",
    org,
  );
  const fleet = useOperationsResource<Fleet>("/routing/own-fleet", org);
  return (
    <Section name="Carrier freight offers">
      {resource.error && <p role="alert">{resource.error}</p>}
      {fleet.data?.vehicles.map((v) => (
        <details key={v.id} className="border-b py-3">
          <summary className="cursor-pointer font-medium">
            {v.registration_number} / routing profile
          </summary>
          <p className="my-2 break-all text-xs">
            Current revision: {v.current_routing_profile_revision_id ?? "None"}
          </p>
          <ActionForm
            name="Save routing-profile revision"
            path={`/vehicles/${v.id}/routing-profile-revisions`}
            etag={v.etag}
            initial={{
              trailer_count: 0,
              supported_cargo_profile_codes: ["ORDINARY_GOODS"],
            }}
            specs={profileSpecs}
            reload={fleet.reload}
          />
        </details>
      ))}
      {resource.data?.items.map((r) => (
        <CarrierOffer
          key={`${org}:${r.id}`}
          rfq={r}
          fleet={fleet.data}
          reload={resource.reload}
        />
      ))}
    </Section>
  );
}

function CarrierOffer({
  rfq,
  fleet,
  reload,
}: {
  rfq: FreightRFQ;
  fleet: Fleet | null;
  reload: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<{
    id: string;
    content_hash: string;
    head_etag: string;
  } | null>(null);
  const [selectionId, setSelectionId] = useState("");
  const categories = rfq.request.service_requirement_codes;
  const initial: Values = {
    currency: "INR",
    offer_kind: "FIRM_OFFER",
    pricing_basis: "FIXED_FOR_CONSIGNMENT_AND_ROUTE",
    source_mode:
      rfq.execution_mode === "SIMULATION" ? "SIMULATION" : "PORTAL_ENTRY",
    route_template_revision_id:
      rfq.request.operational_projection.route_templates[0]?.id,
    charge_components: [
      {
        component_id: crypto.randomUUID(),
        component_code: "BASE_FREIGHT",
        label: "Fixed road freight",
        amount_minor: "0",
      },
    ],
    discount_minor: "0",
    carrier_charged_tax_minor: null,
    tax_treatment: "UNRESOLVED",
    unpriced_carrier_extras_allowed: false,
    service_coverage: categories.map((category_code) => ({
      category_code,
      coverage: "UNKNOWN",
      explanation: "Carrier declaration",
    })),
    contingent_charge_terms: [],
    offered_pickup_window_start: rfq.request.requested_pickup_window_start,
    offered_pickup_window_end: rfq.request.requested_pickup_window_end,
    booking_window_start: rfq.request.requested_pickup_window_start,
    booking_window_end: rfq.request.required_arrival_by,
    offered_delivery_window_start: rfq.request.requested_pickup_window_start,
    offered_delivery_window_end: rfq.request.required_arrival_by,
    valid_from: new Date().toISOString(),
    accept_by: rfq.response_deadline,
    delivery_commitment_kind: "TARGET_ONLY",
  };
  const specs: FieldSpec[] = [
    ...["GOODS_PERMIT", "PERMIT_AUTHORISATION"].map((kind, i): FieldSpec => ({
      path: `transport_evidence_revision_ids.${i}`,
      label: `${kind.replaceAll("_", " ")} reviewed record`,
      kind: "select",
      options: Object.fromEntries(
        fleet?.transport_evidence
          .filter((e) => e.evidence_type === kind)
          .map((e) => [
            e.id,
            `${e.id.slice(0, 8)} / ${e.subject_id.slice(0, 8)}`,
          ]) ?? [],
      ),
    })),
    {
      path: "route_template_revision_id",
      label: "Requested route",
      kind: "select",
      options: Object.fromEntries(
        rfq.request.operational_projection.route_templates.map((t) => [
          t.id,
          `${t.state_sequence?.join(" > ")} / ${t.id.slice(0, 8)}`,
        ]),
      ),
    },
    {
      path: "vehicle_id",
      label: "Owned vehicle",
      kind: "select",
      options: Object.fromEntries(
        fleet?.vehicles.map((v) => [v.id, v.registration_number]) ?? [],
      ),
    },
    {
      path: "routing_vehicle_profile_revision_id",
      label: "Exact routing-profile revision",
      kind: "select",
      options: Object.fromEntries(
        fleet?.vehicles
          .filter((v) => v.current_routing_profile_revision_id)
          .map((v) => [
            v.current_routing_profile_revision_id!,
            v.registration_number,
          ]) ?? [],
      ),
    },
    {
      path: "driver_user_id",
      label: "Nominated driver",
      kind: "select",
      options: Object.fromEntries(
        fleet?.drivers.map((d) => [d.id, d.display_name]) ?? [],
      ),
    },
    {
      path: "charge_components.0.amount_minor",
      label: "Fixed carrier freight (paise)",
      kind: "decimal",
      required: true,
    },
    { path: "discount_minor", label: "Discount (paise)", kind: "decimal" },
    {
      path: "carrier_charged_tax_minor",
      label: "Declared carrier-charged tax (paise)",
      kind: "decimal",
    },
    {
      path: "tax_treatment",
      label: "Declared tax treatment",
      kind: "select",
      options: [
        "DECLARED_SUPPLIER_CHARGED",
        "DECLARED_RECIPIENT_ACCOUNTED",
        "DECLARED_NO_TAX",
        "UNRESOLVED",
      ],
    },
    ...categories.map((c, i): FieldSpec => ({
      path: `service_coverage.${i}.coverage`,
      label: `${c} coverage`,
      kind: "select",
      options: [
        "INCLUDED_IN_QUOTED_PRICE",
        "EXCLUDED_PAYER_COST",
        "NOT_APPLICABLE",
        "UNKNOWN",
      ],
    })),
    ...[
      "offered_pickup_window_start",
      "offered_pickup_window_end",
      "offered_delivery_window_start",
      "offered_delivery_window_end",
      "booking_window_start",
      "booking_window_end",
      "valid_from",
      "accept_by",
    ].map((path): FieldSpec => ({
      path,
      label: `${path.replaceAll("_", " ")} (IST)`,
      kind: "datetime",
      required: true,
    })),
    {
      path: "delivery_terms",
      label: "Service and delivery terms",
      kind: "textarea",
      required: true,
    },
    {
      path: "cancellation_terms",
      label: "Cancellation terms",
      kind: "textarea",
      required: true,
    },
    { path: "tax_note", label: "Tax declaration basis", kind: "textarea" },
    { path: "carrier_offer_reference", label: "Carrier offer reference" },
    {
      path: "source_mode",
      label: "Offer source",
      kind: "select",
      options:
        rfq.execution_mode === "SIMULATION"
          ? ["SIMULATION", "PORTAL_ENTRY", "REVIEWED_QUOTE_DOCUMENT"]
          : ["PORTAL_ENTRY", "REVIEWED_QUOTE_DOCUMENT"],
    },
    {
      path: "quote_document_version_id",
      label: "Reviewed quote document version",
    },
    {
      path: "quote_document_fact_revision_id",
      label: "Effective submitted quote fact revision",
    },
  ];
  return (
    <article className="space-y-4 border-t py-5">
      <h4 className="font-semibold">
        RFQ {rfq.id.slice(0, 8)} / {rfq.execution_mode} / {rfq.lifecycle}
      </h4>
      <Facts
        values={{
          cargo: rfq.request.operational_projection.cargo,
          pickup: rfq.request.operational_projection.pickup,
          drop: rfq.request.operational_projection.drop,
        }}
      />
      {rfq.lifecycle === "OPEN" && (
        <details>
          <summary className="cursor-pointer font-medium">
            Prepare fixed route offer
          </summary>
          <QuoteEditor
            rfqId={rfq.id}
            initial={initial}
            specs={specs}
            reload={reload}
            onSaved={(v) => setDraft(v as typeof draft)}
          />
        </details>
      )}
      {draft && (
        <ActionForm
          name="Submit frozen carrier offer"
          path={`/freight-quote-revisions/${draft.id}/submissions`}
          etag={draft.head_etag}
          initial={{ quote_hash: draft.content_hash }}
          reload={reload}
        />
      )}
      {rfq.quotes.map((q) => (
        <details key={q.id}>
          <summary className="cursor-pointer font-medium">
            Offer {q.id.slice(0, 8)} / {q.lifecycle} / {q.effective_expiration}
          </summary>
          <Facts values={q.quote_json} />
          {q.lifecycle === "SUBMITTED" && (
            <ActionForm
              name="Withdraw offer"
              path={`/freight-quote-revisions/${q.id}/withdrawals`}
              etag={q.head_etag}
              initial={{ quote_hash: q.content_hash }}
              specs={reason}
              reload={reload}
            />
          )}
        </details>
      ))}
      <label className="block text-sm font-medium">
        Selection request
        <select
          aria-label="Selection request"
          className="ml-2 rounded border p-2"
          value={selectionId}
          onChange={(e) => setSelectionId(e.target.value)}
        >
          <option value="">Choose request</option>
          {rfq.selection_requests?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id.slice(0, 8)} / {s.lifecycle}
            </option>
          ))}
        </select>
      </label>
      {selectionId && <CarrierAcceptance key={selectionId} id={selectionId} />}
    </article>
  );
}
function CarrierAcceptance({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<FreightSelection>(
    `/tradetwin-selections/${id}`,
    org,
  );
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!resource.data) return <p role="status">Loading selection request...</p>;
  const s = resource.data;
  return (
    <Section name="Carrier acceptance">
      {s.commitment_id && (
        <FreightCancellation commitmentId={s.commitment_id} />
      )}
      <Facts
        values={{
          state: s.lifecycle,
          proposal_hash: s.proposal_hash,
          route: s.proposal.selected_route_snapshot,
          timing: s.proposal.selected_timing_snapshot,
        }}
      />
      {s.lifecycle === "PENDING_CARRIER_ACCEPTANCE" && (
        <ActionForm
          name="Decide exact freight commitment"
          path={`/tradetwin-selections/${id}/carrier-decisions`}
          etag={s.etag}
          initial={{
            proposal_hash: s.proposal_hash,
            quote_hash: s.quote_hash,
            proposed_assignment_id: s.proposed_assignment_id,
            decision: "ACCEPT",
          }}
          specs={[
            {
              path: "decision",
              label: "Carrier decision",
              kind: "select",
              options: ["ACCEPT", "DECLINE"],
            },
            ...reason,
          ]}
          reload={resource.reload}
        />
      )}
    </Section>
  );
}
const profileSpecs: FieldSpec[] = [
  ...[
    "combined_tare_weight_kg",
    "maximum_authorised_combined_weight_kg",
    "maximum_actual_axle_load_kg",
  ].map((path): FieldSpec => ({
    path,
    label: path.replaceAll("_", " "),
    kind: "decimal",
  })),
  ...[
    "overall_height_mm",
    "overall_width_mm",
    "overall_length_mm",
    "axle_count",
    "trailer_count",
    "speed_cap_kph",
  ].map((path): FieldSpec => ({
    path,
    label: path.replaceAll("_", " "),
    kind: "integer",
  })),
  { path: "toll_vehicle_class_code", label: "Toll vehicle class" },
];
