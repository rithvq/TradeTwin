"use client";
import { useEffect, useState } from "react";
import { RefreshCw, ShieldAlert } from "lucide-react";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import {
  ActionForm,
  Facts,
  Section,
  reason,
} from "@/components/operations/shared";
import { Button } from "@/components/ui/button";
import type { DynamicContext, RecoveryCase } from "@/lib/corridor";
import { type Values } from "@/lib/trades";
import { title } from "@/lib/operations";

export function CorridorDesk({ consignmentId }: { consignmentId: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<DynamicContext>(
    `/consignments/${consignmentId}/dynamic-tradetwin-context`,
    org,
  );
  const action = useOperationalMutation(org, resource.reload);
  const [assessment, setAssessment] = useState<string>("");
  const reload = resource.reload;
  useEffect(() => {
    const timer = window.setInterval(() => void reload(), 30000);
    return () => window.clearInterval(timer);
  }, [reload]);
  const data = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading corridor assessment...</p>;
  return (
    <Section name={`${data.reference} / corridor intelligence`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 font-semibold">
          <ShieldAlert className="size-4" />
          {title(data.impact?.outcome ?? "NOT_ASSESSED")}
        </p>
        <Button variant="outline" onClick={() => void resource.reload()}>
          <RefreshCw className="size-4" />
          Refresh
        </Button>
      </div>
      <Facts
        values={{
          movement_status: data.movement_status,
          source_coverage: data.coverage.status,
          execution_mode: data.execution_mode,
          nominal_arrival_at: data.impact?.nominal_arrival_at ?? null,
          worst_case_arrival_at: data.impact?.worst_case_arrival_at ?? null,
        }}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr>
              {[
                "Reported condition",
                "Route section",
                "Assessment",
                "Evidence",
              ].map((h) => (
                <th className="border-b p-2" key={h}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.impact?.items.map((item, index) => (
              <tr key={`${item.event_revision_id}:${item.edge_key}:${index}`}>
                <td className="border-b p-2 font-medium">
                  {item.headline ?? "Restricted source"}
                </td>
                <td className="border-b p-2">
                  {item.edge_key}
                  <br />
                  <span className="text-secondary">
                    {title(item.spatial_match ?? "UNKNOWN")}
                  </span>
                </td>
                <td className="border-b p-2 font-medium">
                  {title(item.outcome)}
                  <br />
                  <span className="text-secondary">
                    {title(item.temporal_match ?? "UNKNOWN")}
                  </span>
                </td>
                <td className="max-w-80 break-words border-b p-2">
                  {item.source_reference ?? "Owner review required"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.impact?.items.length === 0 && (
        <p className="text-sm text-secondary">
          No matching alerts in these checked sources.
        </p>
      )}
      {data.capabilities.includes("tradetwin.run") &&
        data.current_route_plan_revision_id && (
          <Button
            disabled={action.pending}
            onClick={async () => {
              const result = await action.run<{ id: string }>(
                `/consignments/${consignmentId}/corridor-reassessments`,
                {
                  expected_context_hash: data.dynamic_context_hash,
                  current_route_plan_revision_id:
                    data.current_route_plan_revision_id,
                },
                data.etag,
              );
              if (result) setAssessment(result.id);
            }}
          >
            <RefreshCw className="size-4" />
            Retain current assessment
          </Button>
        )}
      {action.error && <p role="alert">{action.error.message}</p>}
      {assessment && data.capabilities.includes("tradetwin.plan.apply") && (
        <CaseForm
          consignmentId={consignmentId}
          assessmentId={assessment}
          planId={data.current_route_plan_revision_id!}
          reload={resource.reload}
        />
      )}
      {data.recovery_cases.map((row) => (
        <Response key={row.id + row.etag} row={row} reload={resource.reload} />
      ))}
      <details className="border-t pt-3">
        <summary className="cursor-pointer font-medium">
          Source coverage and limitations
        </summary>
        <Facts
          values={{
            coverage: data.coverage,
            limitations: data.impact?.limitations ?? [],
          }}
        />
      </details>
      {data.events.length > 0 && (
        <details>
          <summary className="cursor-pointer font-medium">
            Published event history
          </summary>
          <Facts values={{ events: data.events }} />
        </details>
      )}
    </Section>
  );
}

function CaseForm({
  consignmentId,
  assessmentId,
  planId,
  reload,
}: {
  consignmentId: string;
  assessmentId: string;
  planId: string;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const cn = useOperationsResource<{ etag: string }>(
    `/consignments/${consignmentId}`,
    org,
  );
  if (!cn.data) return null;
  return (
    <ActionForm
      name="Record recovery case"
      path={`/consignments/${consignmentId}/recovery-cases`}
      etag={cn.data.etag}
      initial={{
        assessment_id: assessmentId,
        current_route_plan_revision_id: planId,
      }}
      specs={reason}
      reload={reload}
    />
  );
}

function Response({
  row,
  reload,
}: {
  row: RecoveryCase;
  reload: () => Promise<void>;
}) {
  const initial: Values = {
    observed_at: new Date().toISOString(),
    action: "ACKNOWLEDGE_ALERT",
    location_method: "NONE",
    safe_stop: false,
    reason: "",
  };
  return (
    <article className="space-y-3 border-t py-3">
      <Facts
        values={{
          case_status: row.status,
          protection: row.protection_state,
          reported_motion: row.motion,
          stop_verified: false,
          anchor_approved: false,
          resume_authorised: false,
        }}
      />
      {row.driver_response_allowed && (
        <ActionForm
          name="Record driver response"
          path={`/recovery-cases/${row.id}/driver-responses`}
          etag={row.etag}
          initial={initial}
          reload={reload}
          specs={[
            {
              path: "action",
              label: "Driver response",
              kind: "select",
              options: [
                "ACKNOWLEDGE_ALERT",
                "REPORT_MOVING",
                "CONFIRM_REPORTED_STOPPED",
                "CANNOT_STOP_SAFELY",
                "REQUEST_ASSISTANCE",
              ],
              required: true,
            },
            {
              path: "observed_at",
              label: "Observed at",
              kind: "datetime",
              required: true,
            },
            {
              path: "safe_stop",
              label: "Reported safely stopped",
              kind: "boolean",
            },
            ...reason,
          ]}
        />
      )}
      <details>
        <summary className="cursor-pointer text-sm font-medium">
          Recovery record
        </summary>
        <Facts values={row.case_json} />
      </details>
    </article>
  );
}
