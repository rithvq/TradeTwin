"use client";
import Link from "next/link";
import { Check, ArrowRight } from "lucide-react";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import { Facts, Section } from "@/components/operations/shared";
import { Button } from "@/components/ui/button";
import { title } from "@/lib/operations";
import { displayTime } from "@/lib/trades";
import type { Journey } from "@/lib/product";

const quantities = [
  ["ordered_quantity", "Ordered"],
  ["allocated_quantity", "Allocated"],
  ["dispatched_quantity", "Dispatched"],
  ["current_net_received_quantity", "Net received"],
  ["inspection_accepted_quantity", "Accepted"],
  ["inspection_rejected_quantity", "Rejected"],
  ["inspection_pending_quantity", "Pending inspection"],
  ["final_short_quantity", "Final short"],
];
export function JourneyOverview({
  tradeId,
  module,
}: {
  tradeId: string;
  module: string;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Journey>(
    `/trades/${tradeId}/workspace`,
    org,
  );
  const mutation = useOperationalMutation(org, resource.reload);
  const data = resource.data;
  if (resource.error)
    return <p role="alert">Journey unavailable: {resource.error}</p>;
  if (!data?.commercial) return <p role="status">Loading journey...</p>;
  const tasks = data.tasks.filter(
    (t) => t.module_code === module.toUpperCase(),
  );
  return (
    <section
      aria-label="Trade journey"
      className="min-w-0 space-y-4 border-t border-line py-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="text-lg font-semibold">
          {module === "Shipments" ? "Trade journey" : "Current actions"}
        </h3>
        <span className="text-xs text-secondary">
          {data.projection_freshness} / {displayTime(data.computed_at)}
        </span>
      </div>
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
      {module === "Shipments" && (
        <>
          <Facts
            values={{
              agreement: data.commercial.agreement_status,
              context_version: data.source_context_version,
              bank_settlement: "Not assessed",
              tax_settlement: "Not assessed",
            }}
          />
          {data.fulfilment.ordered_lines.length > 0 && (
            <div className="overflow-x-auto">
              <table
                aria-label="Independent fulfilment quantities"
                className="w-full text-left text-sm"
              >
                <thead>
                  <tr>
                    {["Order line", "UQC", ...quantities.map((q) => q[1])].map(
                      (label) => (
                        <th
                          key={label}
                          className="border-b p-2 whitespace-nowrap"
                        >
                          {label}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {data.fulfilment.ordered_lines.map((line) => (
                    <tr key={line.trade_line_ref}>
                      <th className="p-2 font-medium">{line.description}</th>
                      <td className="p-2">{line.uqc}</td>
                      {quantities.map(([key]) => (
                        <td className="p-2 tabular-nums" key={key}>
                          {line[key]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="divide-y divide-line">
            {data.consignments.map((cn) => (
              <div key={cn.consignment_id} className="space-y-2 py-3">
                <Link
                  href={`/shipments/consignments/${cn.consignment_id}`}
                  className="font-semibold text-accent underline"
                >
                  {cn.consignment_reference}
                </Link>
                <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  {[
                    ["Movement", cn.movement_status],
                    ["Assignment", cn.assignment_status],
                    [
                      "Historical permissions",
                      cn.historical_authorisation_coverage,
                    ],
                    [
                      "Application protection",
                      cn.application_protection_state ?? "None",
                    ],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className="text-secondary">{label}</dt>
                      <dd className="mt-1 font-medium">{title(value)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
          {data.goods_finance && (
            <Section name="Goods finance">
              <Facts values={data.goods_finance} />
            </Section>
          )}
          {data.freight && data.freight.length > 0 && (
            <Section name="Freight contracts">
              {data.freight.map((value, i) => (
                <Facts key={i} values={value} />
              ))}
            </Section>
          )}
        </>
      )}
      <ul className="divide-y divide-line" aria-label="Derived tasks">
        {tasks.map((task) => (
          <li
            className="flex flex-wrap items-start justify-between gap-3 py-3"
            key={task.task_key}
          >
            <div className="min-w-0 flex-1">
              <strong className="block">{task.title}</strong>
              <p className="mt-1 text-sm text-secondary">{task.explanation}</p>
              <span
                className={`mt-2 inline-block text-xs font-semibold ${task.priority === "BLOCKER" ? "text-red-800" : "text-secondary"}`}
              >
                {title(task.status)}
              </span>
            </div>
            <div className="flex gap-2">
              <Button
                size="icon"
                variant="outline"
                aria-label={`Mark seen: ${task.title}`}
                title="Mark seen"
                disabled={mutation.pending || Boolean(task.user_seen_at)}
                onClick={() =>
                  void mutation.run(
                    `/trades/${tradeId}/workspace-task-states`,
                    {
                      task_key: task.task_key,
                      task_basis_hash: task.basis_hash,
                      operation: "SEEN",
                      reason: "Reviewed task summary",
                    },
                    task.user_state_etag ?? undefined,
                  )
                }
              >
                <Check className="size-4" />
              </Button>
              {task.actionable_by_current_user && (
                <Button
                  size="icon"
                  variant="outline"
                  asChild
                  title={`Open ${task.title}`}
                >
                  <Link
                    aria-label={`Open ${task.title}`}
                    href={task.internal_screen_target}
                  >
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {tasks.length === 0 && (
        <p className="text-sm text-secondary">
          No derived tasks for this module.
        </p>
      )}
    </section>
  );
}
