"use client";
import { useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { title, type Operations } from "@/lib/operations";
import { type EvidenceEvent, type Values, displayTime } from "@/lib/trades";
import {
  ActionForm,
  Facts,
  Mode,
  MovementTimeline,
  Refresh,
  Section,
  reason,
} from "./shared";
import { EvidenceUpload } from "./evidence-upload";
import { OperationalGraph } from "./graph";

const modules = [
  "Shipments",
  "Documents",
  "Compliance",
  "Graph",
  "Risk",
  "Optimizer",
  "Regulations",
  "Evidence",
];
export function OperationsWorkspace({ tradeId }: { tradeId: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Operations>(
    `/trades/${tradeId}/operations`,
    org,
  );
  const [module, setModule] = useState("Shipments");
  const data = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading trade operations...</p>;
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Trade operations</h2>
          <Link
            href={`/trades/${tradeId}`}
            className="text-sm text-accent underline"
          >
            Commercial agreement
          </Link>
        </div>
        <div className="flex gap-3">
          <Mode mode={data.execution_mode} />
          <Refresh reload={resource.reload} />
        </div>
      </header>
      <nav
        aria-label="Trade modules"
        className="flex flex-wrap gap-1 border-b border-line"
      >
        {modules.map((name) => (
          <button
            key={name}
            onClick={() => setModule(name)}
            aria-pressed={module === name}
            className={`border-b-2 px-3 py-3 text-sm font-medium ${module === name ? "border-accent text-accent" : "border-transparent text-secondary"}`}
          >
            {name}
          </button>
        ))}
      </nav>
      {module === "Shipments" && (
        <>
          <Section name="Commercial agreement">
            <Facts
              values={{
                agreement_status: data.agreement_status,
                accepted_revision_id: data.accepted_revision_id,
              }}
            />
          </Section>
          <Section name="Quantity allocation">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    {[
                      "Order line",
                      "Ordered",
                      "Reserved",
                      "Available",
                      "UQC",
                    ].map((name) => (
                      <th key={name} className="border-b p-2">
                        {name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.availability.map((line) => (
                    <tr key={line.line_ref}>
                      <td className="p-2 font-medium">{line.description}</td>
                      <td className="p-2">{line.ordered_quantity}</td>
                      <td className="p-2">{line.reserved_quantity}</td>
                      <td className="p-2">{line.available_quantity}</td>
                      <td className="p-2">{line.uqc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.allowed_actions.includes("consignment.plan") && (
              <Button asChild>
                <Link href={`/shipments/trades/${tradeId}/consignments/new`}>
                  <Plus className="size-4" />
                  Allocate consignment
                </Link>
              </Button>
            )}
          </Section>
          <Section name="Movement">
            {data.consignments.length === 0 && (
              <p className="text-sm text-secondary">
                No consignments allocated.
              </p>
            )}
            {data.consignments.map((cn) => (
              <article
                key={cn.id}
                className="space-y-3 border-b border-line py-4"
              >
                <div className="flex flex-wrap justify-between gap-2">
                  <Link
                    className="font-semibold text-accent underline"
                    href={`/shipments/consignments/${cn.id}/assignment`}
                  >
                    {cn.reference}
                  </Link>
                  <span className="text-sm">{title(cn.movement_status)}</span>
                </div>
                <Facts
                  values={{
                    preparation: cn.planning_status,
                    revision_alignment: cn.revision_alignment,
                    active_assignment: cn.active_assignment_id,
                  }}
                />
                <div className="flex flex-wrap gap-3 text-sm">
                  <Link
                    className="text-accent underline"
                    href={`/shipments/consignments/${cn.id}/assignment`}
                  >
                    Transport assignment
                  </Link>
                  <Link
                    className="text-accent underline"
                    href={`/shipments/consignments/${cn.id}/receipt`}
                  >
                    Receipt desk
                  </Link>
                  <Link
                    className="text-accent underline"
                    href={`/shipments/consignments/${cn.id}/inspection`}
                  >
                    Inspection desk
                  </Link>
                </div>
                {cn.movement_status === "NOT_STARTED" &&
                  cn.planning_status !== "CANCELLED" && (
                    <div className="flex flex-wrap gap-4">
                      {cn.allowed_actions.includes("consignment.plan") &&
                        cn.planning_status === "DRAFT" && (
                          <ActionForm
                            name="Prepare consignment"
                            path={`/consignments/${cn.id}/preparations`}
                            etag={cn.etag}
                            reload={resource.reload}
                          />
                        )}{" "}
                      {cn.allowed_actions.includes("consignment.cancel") && (
                        <details>
                          <summary className="cursor-pointer text-sm text-red-800">
                            Cancel reservation
                          </summary>
                          <ActionForm
                            name="Cancel consignment"
                            path={`/consignments/${cn.id}/cancellations`}
                            specs={reason}
                            etag={cn.etag}
                            reload={resource.reload}
                          />
                        </details>
                      )}
                    </div>
                  )}
                <MovementTimeline cn={cn} />
              </article>
            ))}
          </Section>
          <Section name="Buyer receipt">
            {data.consignments.map((cn) => (
              <div key={cn.id} className="mb-4">
                <Link
                  className="text-sm font-semibold text-accent"
                  href={`/shipments/consignments/${cn.id}/receipt`}
                >
                  {cn.reference}
                </Link>
                {cn.receipt_summary?.map((line) => (
                  <Facts
                    key={line.consignment_item_id}
                    values={{
                      goods: line.description,
                      physically_received: `${line.received_quantity} ${line.uqc}`,
                      awaiting_receipt: line.awaiting_receipt_quantity,
                      shortage_after_closure: line.short_quantity,
                    }}
                  />
                ))}
              </div>
            ))}
          </Section>
          <Section name="Inspection">
            {data.consignments.map((cn) => (
              <div key={cn.id} className="mb-4">
                <Link
                  className="text-sm font-semibold text-accent"
                  href={`/shipments/consignments/${cn.id}/inspection`}
                >
                  {cn.reference}
                </Link>
                {cn.receipt_summary?.map((line) => (
                  <Facts
                    key={line.consignment_item_id}
                    values={{
                      goods: line.description,
                      accepted: line.accepted_quantity,
                      rejected: line.rejected_quantity,
                      pending_inspection: line.pending_inspection_quantity,
                    }}
                  />
                ))}
              </div>
            ))}
          </Section>
          <Section name="Disputes">
            {data.disputes.map((d) => (
              <p key={d.id}>
                <Link
                  className="text-accent underline"
                  href={`/shipments/trades/${tradeId}/disputes/${d.id}`}
                >
                  {String(d.dispute_json.summary)}: {title(d.status)}
                </Link>
              </p>
            ))}
            {data.allowed_actions.includes("dispute.open") && (
              <details>
                <summary className="cursor-pointer text-sm font-medium">
                  Open dispute
                </summary>
                <ActionForm
                  name="Open dispute"
                  path={`/trades/${tradeId}/disputes`}
                  initial={{ dispute_type: "OTHER", summary: "" }}
                  specs={[
                    {
                      path: "dispute_type",
                      label: "Dispute type",
                      kind: "select",
                      options: [
                        "SHORTAGE",
                        "DAMAGE",
                        "QUALITY",
                        "TEMPERATURE",
                        "DELAY",
                        "PAYMENT",
                        "OTHER",
                      ],
                    },
                    {
                      path: "summary",
                      label: "Dispute summary",
                      kind: "textarea",
                      required: true,
                    },
                    {
                      path: "requested_remedy",
                      label: "Requested remedy",
                      kind: "textarea",
                    },
                  ]}
                  reload={resource.reload}
                />
              </details>
            )}
          </Section>
          <Section name="Commercial goods payment schedule">
            {data.settlement ? (
              <>
                <Facts
                  values={{
                    schedule_status: data.settlement.schedule_status,
                    pricing_basis: data.settlement.pricing_basis,
                    allocated_goods_amount_paise:
                      data.settlement.net_allocated_minor,
                  }}
                />
                <Button variant="outline" asChild>
                  <Link href={`/shipments/trades/${tradeId}/payments`}>
                    Payment desk
                  </Link>
                </Button>
              </>
            ) : (
              <p className="text-sm text-secondary">
                Finance access is not granted to this membership.
              </p>
            )}
          </Section>
          <Section name="Dispatch readiness">
            <strong>Not assessed</strong>
          </Section>
        </>
      )}
      {module === "Documents" && (
        <Section name="Operational evidence">
          <EvidenceUpload
            tradeId={tradeId}
            consignments={data.consignments}
            records={data.documents}
            reload={resource.reload}
          />
        </Section>
      )}
      {module === "Compliance" && (
        <Section name="Operational preparation">
          <Facts values={{ dispatch_readiness: "Not assessed" }} />
          {data.consignments.map((c) => (
            <p key={c.id}>
              {c.reference}: {c.planning_status} / {c.revision_alignment}
            </p>
          ))}
        </Section>
      )}
      {module === "Graph" && <OperationalGraph graph={data.graph} />}
      {module === "Risk" && (
        <Section name="Operational exceptions">
          {!data.exceptions.length && (
            <p>No recorded operational exceptions.</p>
          )}
          {data.exceptions.map((e, i) => (
            <article
              key={`${e.source_id}-${i}`}
              className="border-b border-line py-3"
            >
              <strong>{title(e.type)}</strong>
              <p className="text-sm text-secondary">
                {e.fact_status} / Verification not assessed
              </p>
              <p className="break-all text-xs">Source: {e.source_id}</p>
              {e.consignment_id && (
                <Link
                  className="text-sm text-accent underline"
                  href={`/shipments/consignments/${e.consignment_id}/${e.type === "SHORTAGE_RECORDED" ? "receipt" : e.type === "GOODS_REJECTED" ? "inspection" : "assignment"}`}
                >
                  Source consignment
                </Link>
              )}
              {!e.consignment_id && e.type.startsWith("PAYMENT_") && (
                <Link
                  className="text-sm text-accent underline"
                  href={`/shipments/trades/${tradeId}/payments`}
                >
                  Source payment records
                </Link>
              )}
            </article>
          ))}
        </Section>
      )}
      {module === "Optimizer" && (
        <Section name="Planning inputs">
          <p className="text-sm text-secondary">
            Planning inputs available. Route and price optimisation arrives in
            Phase 5.
          </p>
          {data.consignments.map((c) => (
            <PlanningPreview key={c.id} id={c.id} label={c.reference} />
          ))}
        </Section>
      )}
      {module === "Regulations" && (
        <Section name="Regulatory context">
          {data.consignments.map((c) => (
            <RegulatoryContext key={c.id} consignment={c} />
          ))}
          <Link className="text-accent underline" href="/dashboard/regulations">
            Regulations
          </Link>
        </Section>
      )}
      {module === "Evidence" && <EvidenceTimeline tradeId={tradeId} />}
    </div>
  );
}

function RegulatoryContext({
  consignment,
}: {
  consignment: Operations["consignments"][number];
}) {
  const { org } = useTradeContext();
  const { data, error } = useOperationsResource<Values>(
    `/consignments/${consignment.id}/planning-context`,
    org,
  );
  const active = consignment.assignments.find(
    (assignment) => assignment.id === consignment.active_assignment_id,
  );
  return (
    <div className="space-y-3 border-b border-line py-3">
      {error && <p role="alert">{error}</p>}
      <Facts
        values={{
          consignment: consignment.reference,
          origin_state: consignment.pickup_address_snapshot.state_code,
          destination_state: consignment.delivery_address_snapshot.state_code,
          goods_and_declared_hsn: data?.goods_lines ?? null,
          movement_purpose: data?.movement_purpose ?? null,
          assignment_reference: consignment.active_assignment_id,
          carrier_organization: active?.carrier_organization_id ?? null,
          vehicle_registration:
            active?.vehicle_snapshot?.registration_number ?? null,
          statutory_dispatch_readiness: "Not assessed",
        }}
      />
    </div>
  );
}

function PlanningPreview({ id, label }: { id: string; label: string }) {
  const { org } = useTradeContext();
  const { data, error } = useOperationsResource<Values>(
    `/consignments/${id}/planning-context`,
    org,
  );
  return (
    <details className="border-b py-3">
      <summary className="cursor-pointer font-medium">{label}</summary>
      {error && <p role="alert">{error}</p>}
      {data && (
        <pre className="mt-3 max-h-96 overflow-auto rounded border bg-surface p-4 text-xs">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </details>
  );
}
function EvidenceTimeline({ tradeId }: { tradeId: string }) {
  const { org } = useTradeContext();
  const [cursor, setCursor] = useState<string | null>(null);
  const resource = useOperationsResource<{
    items: EvidenceEvent[];
    next_cursor: string | null;
  }>(
    `/trades/${tradeId}/evidence-events${cursor ? `?cursor=${cursor}` : ""}`,
    org,
  );
  return (
    <Section name="Immutable evidence">
      <Refresh reload={resource.reload} />
      {resource.error && <p role="alert">{resource.error}</p>}
      <ol className="space-y-4">
        {resource.data?.items.map((e) => (
          <li key={e.id} className="border-b pb-3">
            <strong>{title(e.action)}</strong>
            <p className="text-sm text-secondary">
              {displayTime(e.occurred_at)} / {e.actor_name}
            </p>
            <p className="break-all text-xs">
              {e.subject_type}: {e.subject_id}
            </p>
            <Facts values={e.summary} />
          </li>
        ))}
      </ol>
      {resource.data?.next_cursor && (
        <Button
          variant="outline"
          onClick={() => setCursor(resource.data!.next_cursor)}
        >
          Next evidence page
        </Button>
      )}
      {cursor && (
        <Button variant="outline" onClick={() => setCursor(null)}>
          First evidence page
        </Button>
      )}
    </Section>
  );
}
