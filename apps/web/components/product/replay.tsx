"use client";
import { useEffect, useState } from "react";
import { Play, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import { Facts } from "@/components/operations/shared";
import type { ReplayResult } from "@/lib/product";
import { title } from "@/lib/operations";
import { displayTime } from "@/lib/trades";

export function DecisionReplay({
  runId,
  inputHash,
  engineVersion,
  capabilities,
}: {
  runId: string;
  inputHash: string;
  engineVersion: string;
  capabilities: string[];
}) {
  const { org } = useTradeContext();
  const [requestId, setRequestId] = useState("");
  const mutation = useOperationalMutation(org, async () => {});
  if (!capabilities.includes("evidence.replay.request")) return null;
  async function request(replayKind: string) {
    const result = await mutation.run<{ id: string }>(
      "/evidence/replay-requests",
      {
        subject_type: "TRADETWIN_RUN",
        subject_id: runId,
        replay_kind: replayKind,
        source_manifest_hash: inputHash,
        expected_engine_version: engineVersion,
      },
    );
    if (result) setRequestId(result.id);
  }
  return (
    <section
      aria-label="Historical decision replay"
      className="space-y-4 border-t border-line py-4"
    >
      <h4 className="font-semibold">Historical decision replay</h4>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={mutation.pending}
          onClick={() => void request("RECORDED_DECISION")}
        >
          <Play className="size-4" />
          Read recorded decision
        </Button>
        <Button
          variant="outline"
          disabled={mutation.pending}
          onClick={() => void request("RECOMPUTE_CAPTURED_INPUTS")}
        >
          <RotateCcw className="size-4" />
          Recompute captured inputs
        </Button>
      </div>
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
      {requestId && <ReplayView key={requestId} id={requestId} />}
    </section>
  );
}
function ReplayView({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<ReplayResult>(
    `/evidence/replay-results/${id}`,
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
  if (!data) return <p role="status">Loading historical evidence...</p>;
  return (
    <div className="space-y-3">
      <Facts
        values={{
          job: data.job_state,
          integrity: data.input_integrity ?? "Pending",
          recomputation: data.recomputation ?? "Pending",
          engine: data.engine_version,
          original_as_of: data.original_business_as_of
            ? displayTime(data.original_business_as_of)
            : null,
          current_readiness: "Not assessed by replay",
        }}
      />
      {(data.differences?.length ?? 0) > 0 && (
        <ul className="space-y-2">
          {data.differences?.map((difference, i) => (
            <li className="text-sm" key={i}>
              <strong className="break-all">{difference.path}</strong>
              <p>{difference.reason}</p>
              <span>
                {title(String(difference.original_value))} /{" "}
                {title(String(difference.recomputed_value))}
              </span>
            </li>
          ))}
        </ul>
      )}
      {data.limitations?.map((text) => (
        <p key={text} className="text-sm text-secondary">
          {text}
        </p>
      ))}
    </div>
  );
}
