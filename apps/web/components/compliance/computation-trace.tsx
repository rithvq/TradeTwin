"use client";

import { useOperationsResource } from "@/hooks/use-operations";
import { useTradeContext } from "@/components/trades/trade-context";
import type { ComputationTraceData } from "@/lib/computation-trace";

export function ComputationTrace({ evaluationId }: { evaluationId: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<ComputationTraceData>(
    `/compliance-evaluations/${evaluationId}/computation-trace`,
    org,
  );
  const trace = resource.data;
  return (
    <details className="rounded-lg border border-border p-4">
      <summary className="cursor-pointer font-semibold text-primary">
        How checks were calculated
      </summary>
      {resource.error ? (
        <p role="alert" className="mt-3 text-sm">
          Unable to load calculation details.
        </p>
      ) : !trace ? (
        <p className="mt-3 text-sm text-secondary">
          Loading calculation details…
        </p>
      ) : (
        <ComputationTraceDetails trace={trace} />
      )}
    </details>
  );
}

export function ComputationTraceDetails({
  trace,
  compactRules = false,
}: {
  trace: ComputationTraceData;
  compactRules?: boolean;
}) {
  return (
    <div className="mt-3 space-y-3 text-sm">
      {trace.status === "NOT_RECORDED" && <p>Detail not recorded.</p>}
      {trace.status === "RECORDED" && (
        <>
          <p>
            <strong>{trace.rules_recomputed} recalculated</strong> ·{" "}
            <strong>{trace.rules_reused} reused</strong> · {trace.rules_total}{" "}
            checks
          </p>
          <p className="text-secondary">
            Strategy: {trace.strategy}. Authoritative result:{" "}
            {trace.authoritative_strategy}.
          </p>
          {trace.strategy === "SHADOW" && (
            <p>
              Shadow comparison:{" "}
              {trace.shadow_equivalent ? "equivalent" : "mismatch"};{" "}
              {trace.shadow_rules_reused} calculations eligible for reuse. Full
              evaluation remains authoritative.
            </p>
          )}
          {!!trace.invalidation_reasons.length && (
            <p>
              Reasons: {trace.invalidation_reasons.map(humanise).join(", ")}.
            </p>
          )}
          {compactRules ? (
            <details>
              <summary className="cursor-pointer font-medium">
                Per-rule reasons ({trace.rules_total})
              </summary>
              <RuleReasons rules={trace.rules} />
            </details>
          ) : (
            <RuleReasons rules={trace.rules} />
          )}
        </>
      )}
      <p className="font-medium text-primary">{trace.notice}</p>
    </div>
  );
}

function RuleReasons({ rules }: { rules: ComputationTraceData["rules"] }) {
  return (
    <ul className="mt-2 space-y-1">
      {rules.map((rule) => (
        <li key={rule.rule_code}>
          <strong>{humanise(rule.rule_code)}</strong>:{" "}
          {humanise(rule.disposition)} (
          {rule.reason_codes.map(humanise).join(", ")})
        </li>
      ))}
    </ul>
  );
}

function humanise(value: string) {
  return value.toLowerCase().replaceAll("_", " ");
}
