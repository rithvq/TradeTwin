import { dispatchLabel } from "@/lib/dispatch-dashboard";
import { displayTime } from "@/lib/trades";

export function DispatchStatus({ value }: { value: string }) {
  const positive = [
    "READY",
    "ACTIVE",
    "COMPLETE",
    "PASSED",
    "RECORDED",
    "CURRENT",
  ].includes(value);
  return (
    <span
      className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold capitalize ${positive ? "border-teal-300 bg-teal-50 text-teal-900" : "border-line bg-soft text-ink"}`}
    >
      {dispatchLabel(value)}
    </span>
  );
}

export function DispatchFacts({
  facts,
}: {
  facts: Record<string, string | number | boolean | null>;
}) {
  return (
    <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
      {Object.entries(facts)
        .filter(([, value]) => value !== null)
        .map(([key, value]) => (
          <div key={key} className="min-w-0">
            <dt className="capitalize text-secondary">{dispatchLabel(key)}</dt>
            <dd className="break-words font-medium text-ink">
              {typeof value === "boolean"
                ? value
                  ? "Yes"
                  : "No"
                : key.endsWith("_at") || key === "valid_from"
                  ? displayTime(String(value))
                  : String(value)}
            </dd>
          </div>
        ))}
    </dl>
  );
}
