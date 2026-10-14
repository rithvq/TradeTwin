"use client";
import { useState } from "react";
import Link from "next/link";
import { Play, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/operations/shared";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationalMutation } from "@/hooks/use-operations";
import type { DemoRun, DemoWorkspace } from "@/lib/product";
import { title } from "@/lib/operations";

export function GuidedDemo({ capabilities }: { capabilities: string[] }) {
  const { org } = useTradeContext();
  const [workspace, setWorkspace] = useState<DemoWorkspace | null>(null);
  const [run, setRun] = useState<DemoRun | null>(null);
  const mutation = useOperationalMutation(org, async () => {});
  if (!capabilities.includes("demo.workspace.create")) return null;
  const next = workspace?.scenario.steps[run?.receipts.length ?? 0];
  return (
    <Section name="Guided simulation">
      <p className="text-sm text-secondary">
        Bounded demonstration. Recovery execution and full scenario
        qualification remain unavailable.
      </p>
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
      {!workspace && (
        <Button
          disabled={mutation.pending}
          onClick={async () => {
            const value = await mutation.run<DemoWorkspace>(
              "/demo/workspaces",
              { scenario_code: "BOUNDED_JOURNEY_V1" },
            );
            if (value) setWorkspace(value);
          }}
        >
          <Play className="size-4" />
          Create simulation workspace
        </Button>
      )}
      {workspace && (
        <div className="space-y-4">
          <p className="text-sm font-semibold">
            SIMULATION / {workspace.state}
          </p>
          {!run && (
            <Button
              disabled={mutation.pending}
              onClick={async () => {
                const value = await mutation.run<DemoRun>(
                  `/demo/workspaces/${workspace.id}/runs`,
                  { scenario_manifest_hash: workspace.scenario_manifest_hash },
                  workspace.etag,
                );
                if (value) setRun(value);
              }}
            >
              <Play className="size-4" />
              Start registered demo
            </Button>
          )}
          {run && (
            <>
              <p role="status">{title(run.status)}</p>
              <ol className="space-y-2">
                {run.receipts.map((receipt) => (
                  <li key={receipt.id} className="text-sm">
                    {title(receipt.step_code)}:{" "}
                    <strong>{receipt.receipt.status}</strong>
                  </li>
                ))}
              </ol>
              {next && run.status === "RUNNING" && (
                <Button
                  disabled={mutation.pending}
                  onClick={async () => {
                    const value = await mutation.run<DemoRun>(
                      `/demo/runs/${run.id}/step-executions`,
                      { step_code: next.step_code },
                      run.etag,
                    );
                    if (value) {
                      setRun(value);
                      setWorkspace({
                        ...workspace,
                        etag: value.workspace_etag,
                        trade_id: value.trade_id,
                      });
                    }
                  }}
                >
                  <Play className="size-4" />
                  {title(next.step_code)}
                </Button>
              )}
              {run.trade_id && (
                <Link
                  href={`/trades/${run.trade_id}`}
                  className="block text-sm text-accent underline"
                >
                  Open ordinary commercial workspace
                </Link>
              )}
            </>
          )}
          <Button
            variant="outline"
            disabled={mutation.pending}
            onClick={async () => {
              const value = await mutation.run<DemoWorkspace>(
                `/demo/workspaces/${workspace.id}/reset-successors`,
                { scenario_code: "BOUNDED_JOURNEY_V1" },
                workspace.etag,
              );
              if (value) {
                setWorkspace(value);
                setRun(null);
              }
            }}
          >
            <RotateCcw className="size-4" />
            Create fresh successor
          </Button>
        </div>
      )}
    </Section>
  );
}
