export type ComputationTraceData = {
  status: "RECORDED" | "NOT_RECORDED";
  strategy: "FULL" | "SHADOW" | "INCREMENTAL" | null;
  authoritative_strategy: "FULL" | "INCREMENTAL" | null;
  rules_total: number;
  rules_recomputed: number;
  rules_reused: number;
  shadow_rules_reused: number;
  shadow_equivalent: boolean | null;
  invalidation_reasons: string[];
  rules: { rule_code: string; disposition: string; reason_codes: string[] }[];
  notice: string;
};
