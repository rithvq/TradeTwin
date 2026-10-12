"use client";
import { type ReactNode } from "react";
import { AlertCircle } from "lucide-react";
import { label, type DocumentRecord } from "@/lib/document-desk";

export function Status({ value }: { value: string | null }) {
  const text = value ?? "Not started";
  const tone = ["FAIL", "INVALID", "REJECTED", "DISCREPANCIES_FOUND"].includes(
    text,
  )
    ? "bg-red-50 text-red-900 border-red-200"
    : [
          "STALE",
          "PARTIAL",
          "QUARANTINED",
          "UNKNOWN",
          "INSUFFICIENT_DATA",
          "KEY_UNAVAILABLE",
          "NOT_CONFIGURED",
          "UNAVAILABLE",
        ].includes(text)
      ? "bg-amber-50 text-amber-900 border-amber-200"
      : "bg-surface-raised text-primary border-line";
  return (
    <span
      className={`inline-flex max-w-full whitespace-normal rounded border px-2 py-1 text-xs font-medium ${tone}`}
    >
      {label(text)}
    </span>
  );
}
export function Dimensions({
  document,
}: {
  document: Pick<DocumentRecord, "status_dimensions">;
}) {
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
      {Object.entries(document.status_dimensions).map(([name, value]) => (
        <div key={name} className="min-w-0">
          <dt className="mb-1 text-xs text-secondary">{label(name)}</dt>
          <dd>
            <Status value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function Panel({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0 space-y-4 border-t border-line py-5">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}
export function ErrorNotice({ message }: { message: string }) {
  return message ? (
    <p
      role="alert"
      className="flex items-start gap-2 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-900"
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0" />
      {message}
    </p>
  ) : null;
}
