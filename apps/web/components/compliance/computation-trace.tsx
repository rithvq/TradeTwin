"use client";

import { useOperationsResource } from "@/hooks/use-operations";
import { useTradeContext } from "@/components/trades/trade-context";

type Trace = {
  status: "RECORDED" | "NOT_RECORDED";
  strategy: string | null;
  authoritative_strategy: string | null;
  rules_total: number;
  rules_recomputed: number;
  rules_reused: number;
  shadow_rules_reused: number;
  shadow_equivalent: boolean | null;
  invalidation_reasons: string[];
  rules: { rule_code: string; disposition: string; reason_codes: string[] }[];
  notice: string;
};

export function ComputationTrace({ evaluationId }: { evaluationId: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Trace>(
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
        <div className="mt-3 space-y-3 text-sm">
          {trace.status === "RECORDED" && (
            <>
              <p>
                <strong>{trace.rules_recomputed} recalculated</strong> ·{" "}
                <strong>{trace.rules_reused} reused</strong> ·{" "}
                {trace.rules_total} checks
              </p>
              <p className="text-secondary">
                Strategy: {trace.strategy}. Authoritative result:{" "}
                {trace.authoritative_strategy}.
              </p>
              {trace.strategy === "SHADOW" && (
                <p>
                  Shadow comparison:{" "}
                  {trace.shadow_equivalent ? "equivalent" : "mismatch"};{" "}
                  {trace.shadow_rules_reused} calculations eligible for reuse.
                  Full evaluation remains authoritative.
                </p>
              )}
              {!!trace.invalidation_reasons.length && (
                <p>
                  Reasons: {trace.invalidation_reasons.map(humanise).join(", ")}
                  .
                </p>
              )}
              <ul className="space-y-1">
                {trace.rules.map((rule) => (
                  <li key={rule.rule_code}>
                    <strong>{humanise(rule.rule_code)}</strong>:{" "}
                    {humanise(rule.disposition)} (
                    {rule.reason_codes.map(humanise).join(", ")})
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="font-medium text-primary">{trace.notice}</p>
        </div>
      )}
    </details>
  );
}

function humanise(value: string) {
  return value.toLowerCase().replaceAll("_", " ");
}
