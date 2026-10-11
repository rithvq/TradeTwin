export function statusBadgeClasses(status: string): string {
  const base = "whitespace-nowrap rounded px-3 py-1.5 text-sm font-medium";
  if (status === "COMPLIANT") {
    return `${base} bg-emerald-100 text-emerald-900`;
  }
  if (status === "CONDITIONALLY_COMPLIANT") {
    return `${base} bg-amber-100 text-amber-900`;
  }
  if (status === "NON_COMPLIANT") {
    return `${base} bg-red-100 text-red-900`;
  }
  return `${base} bg-slate-100 text-slate-700`;
}
