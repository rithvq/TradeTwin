"use client";
import { useEffect, useState } from "react";
import { ShieldCheck, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Section,
  Facts,
  ActionForm,
  reason,
} from "@/components/operations/shared";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import type { ReadinessContext, ReadinessRun } from "@/lib/product";
import { title } from "@/lib/operations";

export function AssuranceDesk({ capabilities }: { capabilities: string[] }) {
  return capabilities.includes("readiness.read") ? (
    <Desk capabilities={capabilities} />
  ) : null;
}
function Desk({ capabilities }: { capabilities: string[] }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<ReadinessContext>(
    "/readiness/context",
    org,
  );
  const mutation = useOperationalMutation(org, resource.reload);
  const [runId, setRunId] = useState("");
  const data = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading deployment assurance...</p>;
  return (
    <Section name="Deployment assurance">
      <Facts
        values={{
          qualification: data.qualification_outcome,
          activation: data.activation_state ?? "Not activated",
        }}
      />
      {data.limitations.map((text) => (
        <p className="text-sm text-secondary" key={text}>
          {text}
        </p>
      ))}
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
      <div className="flex flex-wrap gap-2">
        <Button
          size="icon"
          variant="outline"
          aria-label="Refresh deployment manifest"
          title="Refresh deployment manifest"
          onClick={() => void resource.reload()}
        >
          <RefreshCw className="size-4" />
        </Button>
        {capabilities.includes("readiness.run") && data.manifest_hash && (
          <Button
            disabled={mutation.pending}
            onClick={async () => {
              const result = await mutation.run<{ id: string }>(
                "/readiness/runs",
                {
                  expected_manifest_hash: data.manifest_hash,
                  check_suite_code: "PRODUCT_ASSURANCE_V1",
                },
              );
              if (result) setRunId(result.id);
            }}
          >
            <ShieldCheck className="size-4" />
            Run registered assurance
          </Button>
        )}
      </div>
      {data.manifest && (
        <details>
          <summary className="cursor-pointer text-sm font-medium">
            Nonsecret deployment manifest
          </summary>
          <Facts values={data.manifest} />
        </details>
      )}
      {data.deployment_id && capabilities.includes("deployment.pause") && (
        <ActionForm
          name="Pause new binding and movement permissions"
          path={`/deployments/${data.deployment_id}/pauses`}
          initial={{
            reason: "",
            pause_binding_actions: true,
            pause_movement_permissions: true,
          }}
          specs={reason}
          etag={data.etag}
          reload={resource.reload}
        />
      )}
      {runId && <Result key={runId} id={runId} />}
    </Section>
  );
}
function Result({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<ReadinessRun>(
    `/readiness/runs/${id}`,
    org,
  );
  const data = resource.data;
  const reload = resource.reload;
  useEffect(() => {
    if (!data || !["QUEUED", "RUNNING"].includes(data.job_state)) return;
    const timer = window.setInterval(() => void reload(), 2000);
    return () => window.clearInterval(timer);
  }, [data, reload]);
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading assurance result...</p>;
  return (
    <div className="space-y-3">
      <strong role="status">
        {data.qualification_outcome ?? data.job_state}
      </strong>
      <ul className="divide-y divide-line">
        {data.checks.map((check) => (
          <li key={check.id} className="py-3 text-sm">
            <span className="mr-3 font-medium">{title(check.check_code)}</span>
            <strong
              className={
                check.outcome === "FAIL" ? "text-red-800" : "text-secondary"
              }
            >
              {check.outcome}
            </strong>
            <p className="mt-1">{check.observation.reason}</p>
            <span className="text-xs text-secondary">{check.provenance}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
