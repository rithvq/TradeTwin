"use client";
import { useEffect } from "react";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { Facts } from "@/components/operations/shared";
import type { Values } from "@/lib/trades";

export function RouteGeneration({
  id,
  reload,
}: {
  id: string;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<{
    job_state: string;
    result: Values | null;
  }>(`/route-generation-jobs/${id}`, org);
  const refresh = resource.reload;
  const state = resource.data?.job_state;
  useEffect(() => {
    if (state === "COMPLETED") {
      void reload();
      return;
    }
    if (state === "FAILED" || state === "CANCELLED") return;
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [state, refresh, reload]);
  return (
    <div aria-live="polite">
      <p className="text-sm">Route generation / {state ?? "Queued"}</p>
      {resource.error && <p role="alert">{resource.error}</p>}
      {resource.data?.result && <Facts values={resource.data.result} />}
    </div>
  );
}
