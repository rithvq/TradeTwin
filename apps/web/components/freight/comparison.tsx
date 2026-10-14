"use client";
import { useEffect, useState } from "react";
import { Check, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import {
  type FreightContext,
  type FreightRun,
  freightMoney,
} from "@/lib/freight";
import { displayTime, tradeRequest } from "@/lib/trades";
import { ActionForm, Facts, Section } from "@/components/operations/shared";
import { title } from "@/lib/operations";
import { DecisionReplay } from "@/components/product/replay";

export function FreightComparison({
  runId,
  context,
  reload,
  module = "Optimizer",
}: {
  runId: string;
  context: FreightContext;
  reload: () => Promise<void>;
  module?: string;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<FreightRun>(
    `/tradetwin-runs/${runId}`,
    org,
  );
  const [scenario, setScenario] = useState("BASE");
  const [objective, setObjective] = useState("LOWEST_COMPARABLE_COST");
  const [downloadError, setDownloadError] = useState("");
  const mutation = useOperationalMutation(org, reload);
  const data = resource.data;
  const reloadJob = resource.reload;
  useEffect(() => {
    if (!data || !["QUEUED", "RUNNING", "RETRYING"].includes(data.job_state))
      return;
    const poll = window.setInterval(() => void reloadJob(), 2000);
    return () => window.clearInterval(poll);
  }, [data, reloadJob]);
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading comparison...</p>;
  if (data.job_state !== "COMPLETED")
    return (
      <Section name="TradeTwin job">
        <p role="status">{title(data.job_state)}</p>
        <Button variant="outline" onClick={() => void resource.reload()}>
          Refresh job
        </Button>
      </Section>
    );
  const ranked = data.rankings?.[scenario]?.[objective] ?? [];
  const recommendation = ranked[0];
  const scenarios = Object.keys(data.candidates[0]?.scenarios ?? { BASE: {} });
  async function download() {
    try {
      const manifest = await tradeRequest(
        `/tradetwin-runs/${runId}/evidence-manifest`,
        org,
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(manifest, null, 2)], {
          type: "application/json",
        }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `tradetwin-${runId}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setDownloadError(
        error instanceof Error ? error.message : "Export unavailable",
      );
    }
  }
  return (
    <Section
      name={
        module === "Risk"
          ? "Planning constraints and uncertainty"
          : module === "Evidence"
            ? "Decision replay"
            : "TradeTwin baseline comparison"
      }
    >
      {module === "Evidence" && data.engine_version && (
        <DecisionReplay
          runId={runId}
          inputHash={data.input_hash}
          engineVersion={data.engine_version}
          capabilities={context.capabilities}
        />
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <strong>
          {data.execution_mode} / {data.freshness}
        </strong>
        <span className="text-sm text-secondary">
          As of {displayTime(data.evaluated_as_of)}
        </span>
        <Button variant="outline" onClick={() => void download()}>
          <Download className="size-4" />
          Evidence manifest
        </Button>
      </div>
      {downloadError && <p role="alert">{downloadError}</p>}
      {data.freshness !== "CURRENT" && (
        <p role="alert" className="font-semibold text-amber-900">
          Historical comparison. Changed or expired inputs require a new BASE
          run.
        </p>
      )}
      <div className="flex flex-wrap gap-4">
        <label className="text-sm font-medium">
          Scenario
          <select
            className="ml-2 rounded border p-2"
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
          >
            {scenarios.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        {data.price_visible && (
          <label className="text-sm font-medium">
            Objective
            <select
              className="ml-2 rounded border p-2"
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
            >
              {[
                "LOWEST_COMPARABLE_COST",
                "EARLIEST_ESTIMATED_ARRIVAL",
                "BALANCED",
              ].map((s) => (
                <option key={s} value={s}>
                  {title(s)}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {recommendation && (
        <p className="font-semibold">
          {title(objective)}: offer{" "}
          {data.candidates
            .find((c) => c.candidate_id === recommendation.candidate_id)
            ?.quote_revision_id.slice(0, 8)}
          . {recommendation.explanation}
        </p>
      )}
      {data.eligible_baseline_comparison && (
        <p className="text-sm font-medium">
          Offer {data.eligible_baseline_comparison.baseline_offer} arrives
          earlier than offer{" "}
          {data.eligible_baseline_comparison.lowest_cost_offer} for{" "}
          {freightMoney(
            data.eligible_baseline_comparison
              .additional_cost_for_earlier_arrival_minor,
          )}{" "}
          more. {data.eligible_baseline_comparison.basis}
        </p>
      )}
      <div className="overflow-x-auto">
        <table
          aria-label="Freight candidate comparison"
          className="w-full text-left text-sm"
        >
          <thead>
            <tr>
              {[
                "Offer / route",
                "Distance / arrival",
                ...(data.price_visible
                  ? [
                      "Carrier quote",
                      "Additional estimates",
                      "Comparable total / rank",
                    ]
                  : []),
                "Planning outcome",
                "Decision",
              ].map((h) => (
                <th key={h} className="border-b p-3 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.candidates.map((c) => {
              const s = c.scenarios[scenario] ?? c.scenarios.BASE;
              const rank = ranked.find(
                (r) => r.candidate_id === c.candidate_id,
              );
              return (
                <tr key={c.candidate_id} className="border-b">
                  <td className="p-3 font-medium">
                    Offer {c.offer_label ?? c.quote_revision_id.slice(0, 8)}
                    <p>
                      {s.route.state_sequence?.join(" > ") ??
                        "Corridor unknown"}
                    </p>
                  </td>
                  <td className="p-3">
                    {(s.route.distance_meters / 1000).toFixed(1)} km
                    <p>{displayTime(s.estimated_arrival_at)}</p>
                  </td>
                  {data.price_visible && (
                    <>
                      <td className="p-3">
                        {freightMoney(s.cost?.carrier_payable_minor)}
                      </td>
                      <td className="p-3">
                        {freightMoney(s.cost?.external_cost_minor)}
                        <p>
                          Tax cash estimate:{" "}
                          {freightMoney(
                            s.cost?.recipient_tax_cash_estimate_minor,
                          )}
                        </p>
                        <p>
                          Waiting:{" "}
                          {freightMoney(
                            s.cost?.scenario_contingent_charge_minor,
                          )}
                        </p>
                      </td>
                      <td className="p-3 font-semibold">
                        {freightMoney(s.cost?.comparison_total_minor)}
                        <p>
                          {rank
                            ? `Rank ${rank.rank}${rank.pareto_member ? " / Pareto" : ""}`
                            : "Unranked"}
                        </p>
                        <span className="text-xs font-normal">
                          {title(s.cost?.cost_completeness ?? "UNKNOWN")}
                        </span>
                        {s.cost?.comparison_total_minor == null && (
                          <p className="text-xs font-normal">
                            Known partial:{" "}
                            {freightMoney(s.cost?.known_partial_subtotal_minor)}
                          </p>
                        )}
                      </td>
                    </>
                  )}
                  <td className="p-3 font-medium">
                    <span>{title(s.planning_outcome)}</span>
                    <p className="text-xs text-secondary">
                      {s.why_excluded.map(title).join(", ")}
                    </p>
                  </td>
                  <td className="p-3">
                    {module === "Optimizer" &&
                      context.capabilities.includes(
                        "tradetwin.selection.prepare",
                      ) && (
                        <Button
                          variant="outline"
                          disabled={
                            mutation.pending ||
                            scenario !== "BASE" ||
                            data.freshness !== "CURRENT" ||
                            s.planning_outcome !== "SUPPORTED_PLAN" ||
                            s.cost?.cost_completeness === "INCOMPLETE"
                          }
                          onClick={() =>
                            void mutation.run(
                              `/consignments/${context.consignment_id}/tradetwin-selections`,
                              {
                                run_id: data.id,
                                candidate_id: c.candidate_id,
                                candidate_hash: c.candidate_hash,
                                quote_revision_id: c.quote_revision_id,
                                quote_hash: c.quote_hash,
                                scenario_code: "BASE",
                                expected_existing_assignment_id:
                                  context.current_assignment_id,
                                expected_consignment_row_version:
                                  context.expected_consignment_row_version,
                                expected_context_version:
                                  context.compliance_context_version,
                              },
                              context.consignment_etag,
                            )
                          }
                        >
                          <Check className="size-4" />
                          Propose
                        </Button>
                      )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {mutation.error && (
        <p role="alert">
          {mutation.error.code}: {mutation.error.message}
        </p>
      )}
      {data.candidates.map((c) => {
        const s = c.scenarios[scenario] ?? c.scenarios.BASE;
        return (
          <details key={c.candidate_id} className="border-b py-3">
            <summary className="cursor-pointer font-medium">
              Offer {c.offer_label ?? c.quote_revision_id.slice(0, 8)} /
              constraints and sources
            </summary>
            <ul className="mt-3 space-y-2">
              {s.planning_constraint_results.map((r, i) => (
                <li key={`${r.requirement_code}-${i}`} className="text-sm">
                  <strong>
                    {title(r.requirement_code)}: {r.outcome}
                  </strong>
                  <p className="text-secondary">{r.explanation}</p>
                </li>
              ))}
            </ul>
            <Facts
              values={{
                route_source: s.route.data_provenance,
                remaining_dispatch_work: s.post_selection_actions,
                limitations: s.informational_limitations,
              }}
            />
            {s.cost && (
              <details>
                <summary className="cursor-pointer text-sm font-medium">
                  Exact calculation steps
                </summary>
                <Facts
                  values={{
                    steps: s.cost.calculation_steps,
                    unknown_categories: s.cost.unknown_cost_categories,
                  }}
                />
              </details>
            )}
          </details>
        );
      })}
      {module === "Optimizer" &&
        context.capabilities.includes("tradetwin.run") &&
        data.freshness === "CURRENT" && (
          <details className="border-t py-3">
            <summary className="cursor-pointer font-medium">
              What-if scenario
            </summary>
            <ActionForm
              name="Run what-if comparison"
              path={`/tradetwin-runs/${runId}/scenario-runs`}
              etag={context.context_etag}
              initial={{
                scenario: {
                  scenario_code: "EXTRA_WAIT",
                  label: "Origin wait +46 minutes",
                  delay_placement: "ORIGIN_BEFORE_DEPARTURE",
                  additional_wait_minutes: 46,
                  additional_stop_minutes: 0,
                  assumption_origin: "USER_INPUT",
                },
                objective,
                balanced_weights: {
                  cost_basis_points: 5000,
                  time_basis_points: 5000,
                },
              }}
              specs={[
                {
                  path: "scenario.label",
                  label: "Scenario name",
                  required: true,
                },
                {
                  path: "scenario.scenario_code",
                  label: "Scenario type",
                  kind: "select",
                  options: ["EXTRA_WAIT", "EXTRA_STOP"],
                },
                {
                  path: "scenario.delay_placement",
                  label: "Delay location",
                  kind: "select",
                  options: [
                    "ORIGIN_BEFORE_DEPARTURE",
                    "IN_TRANSIT",
                    "DESTINATION_UNLOADING",
                  ],
                },
                {
                  path: "scenario.additional_wait_minutes",
                  label: "Additional wait (minutes)",
                  kind: "integer",
                },
                {
                  path: "scenario.additional_stop_minutes",
                  label: "Additional stop (minutes)",
                  kind: "integer",
                },
                {
                  path: "scenario.assumption_note",
                  label: "Assumption basis",
                  kind: "textarea",
                },
                {
                  path: "objective",
                  label: "Scenario objective",
                  kind: "select",
                  options: [
                    "LOWEST_COMPARABLE_COST",
                    "EARLIEST_ESTIMATED_ARRIVAL",
                    "BALANCED",
                  ],
                },
                {
                  path: "balanced_weights.cost_basis_points",
                  label: "Cost weight (basis points)",
                  kind: "integer",
                },
                {
                  path: "balanced_weights.time_basis_points",
                  label: "Time weight (basis points)",
                  kind: "integer",
                },
              ]}
              reload={reload}
            />
          </details>
        )}
    </Section>
  );
}
