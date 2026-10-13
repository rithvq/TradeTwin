"use client";
import { useState } from "react";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { type FreightContext } from "@/lib/freight";
import {
  ActionForm,
  Facts,
  Section,
  reason,
} from "@/components/operations/shared";
import { FreightComparison } from "./comparison";
import { FreightPlanning } from "./planning";
import { FreightCosts } from "./costs";
import { FreightCancellation } from "./cancellation";
import { FreightApproval } from "./approval";
import { OperationalGraph } from "@/components/operations/graph";
import type { Operations } from "@/lib/operations";

export function FreightDesk({
  consignmentId,
  module,
}: {
  consignmentId: string;
  module: string;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<FreightContext>(
    `/consignments/${consignmentId}/tradetwin-context`,
    org,
  );
  const [selectedRun, setSelectedRun] = useState("");
  const data = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading freight context...</p>;
  const runId = selectedRun || data.runs[0]?.id;
  const proposal = data.selection;
  const valid =
    proposal &&
    ["PENDING_APPROVALS", "PENDING_CARRIER_ACCEPTANCE"].includes(
      proposal.lifecycle,
    );
  return (
    <section
      aria-label={`Freight planning ${data.reference}`}
      className="min-w-0 space-y-4 border-t py-5"
    >
      <h3 className="text-lg font-semibold">{data.reference} / freight plan</h3>
      {module === "Shipments" && (
        <Facts
          values={{
            payer_basis: data.freight_payer_basis,
            active_route: data.route_plan?.route_plan_json ?? null,
            selection_state: proposal?.lifecycle ?? "No selected plan",
            dispatch:
              "Fresh Phase 4 evaluation and action-bound authorisation required",
          }}
        />
      )}
      {module === "Optimizer" && (
        <>
          <Facts
            values={{
              payer_basis: data.freight_payer_basis,
              execution_mode: data.execution_mode,
              current_assignment: data.current_assignment_id,
            }}
          />
          <FreightPlanning context={data} reload={resource.reload} />
          {data.price_visible && (
            <FreightCosts context={data} reload={resource.reload} />
          )}
        </>
      )}
      {data.runs.length > 0 &&
        ["Optimizer", "Risk", "Evidence", "Graph"].includes(module) && (
          <>
            <label className="block min-w-0 text-sm font-medium">
              Stored comparison
              <select
                className="mt-2 block w-full max-w-full min-w-0 rounded border p-2"
                value={runId}
                onChange={(e) => setSelectedRun(e.target.value)}
              >
                {data.runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.evaluated_as_of} / {r.job_state} / {r.freshness}
                  </option>
                ))}
              </select>
            </label>
            {runId &&
              (module === "Graph" ? (
                <FreightGraph runId={runId} />
              ) : (
                <FreightComparison
                  key={runId}
                  runId={runId}
                  context={data}
                  reload={resource.reload}
                  module={module}
                />
              ))}
          </>
        )}
      {proposal?.commitment_id &&
        ["Shipments", "Optimizer"].includes(module) &&
        (data.capabilities.includes("freight.commit.approve") ||
          data.capabilities.includes("tradetwin.plan.apply")) && (
          <FreightCancellation commitmentId={proposal.commitment_id} />
        )}
      {proposal && ["Optimizer", "Shipments", "Evidence"].includes(module) && (
        <Section name="Transport-plan commitment">
          <strong>{proposal.lifecycle}</strong>
          <details>
            <summary className="cursor-pointer text-sm font-medium">
              Selected route, amounts and decision evidence
            </summary>
            <Facts
              values={{
                proposal_hash: proposal.proposal_hash,
                quote_hash: proposal.quote_hash,
                selected_route: proposal.proposal.selected_route_snapshot,
                selected_timing: proposal.proposal.selected_timing_snapshot,
                cost: proposal.proposal.comparison_cost_snapshot ?? null,
                decisions: proposal.decisions,
              }}
            />
          </details>
          {valid &&
            org === data.freight_payer_organisation_id &&
            data.capabilities.includes("freight.commit.approve") && (
              <FreightApproval
                key={proposal.id}
                selection={proposal}
                role="payer"
                reload={resource.reload}
              />
            )}
          {valid &&
            data.capabilities.includes("tradetwin.plan.apply") &&
            org === data.coordinating_organisation_id &&
            data.coordinating_organisation_id !==
              data.freight_payer_organisation_id && (
              <FreightApproval
                key={proposal.id}
                selection={proposal}
                role="coordinator"
                reload={resource.reload}
              />
            )}
          {valid &&
            data.capabilities.includes("tradetwin.selection.prepare") && (
              <ActionForm
                name="Cancel uncommitted proposal"
                path={`/tradetwin-selections/${proposal.id}/cancellations`}
                etag={proposal.etag}
                specs={reason}
                reload={resource.reload}
              />
            )}
        </Section>
      )}
    </section>
  );
}

function FreightGraph({ runId }: { runId: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Operations["graph"]>(
    `/tradetwin-runs/${runId}/graph`,
    org,
  );
  return resource.data ? (
    <section aria-label="Freight decision relationships">
      <OperationalGraph graph={resource.data} />
    </section>
  ) : (
    <p role="status">{resource.error || "Loading freight relationships..."}</p>
  );
}
