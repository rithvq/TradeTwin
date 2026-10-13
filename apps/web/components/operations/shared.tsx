"use client";
import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Check, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationalMutation } from "@/hooks/use-operations";
import { displayTime, type Values } from "@/lib/trades";
import { title, type Consignment } from "@/lib/operations";

export function Mode({ mode }: { mode: string }) {
  return (
    <strong
      className={`inline-flex rounded border px-3 py-1 text-xs ${mode === "SIMULATION" ? "border-amber-400 bg-amber-50 text-amber-900" : "border-line"}`}
    >
      {mode}
    </strong>
  );
}
export function Section({
  name,
  children,
}: {
  name: string;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0 space-y-4 border-t border-line py-5">
      <h3 className="text-lg font-semibold">{name}</h3>
      {children}
    </section>
  );
}
export function Refresh({ reload }: { reload: () => Promise<void> }) {
  return (
    <Button
      variant="outline"
      size="icon"
      title="Refresh operational facts"
      aria-label="Refresh operational facts"
      onClick={() => void reload()}
    >
      <RefreshCw className="size-4" />
    </Button>
  );
}
export function ActionForm({
  name,
  path,
  specs = [],
  initial = {},
  etag,
  reload,
  method = "POST",
  onSaved,
}: {
  name: string;
  path: string;
  specs?: FieldSpec[];
  initial?: Values;
  etag?: string;
  reload: () => Promise<void>;
  method?: string;
  onSaved?: (result: unknown) => void;
}) {
  const { org } = useTradeContext();
  return (
    <ActionFields
      key={`${org}:${path}:${method}`}
      {...{
        name,
        path,
        specs,
        initial,
        etag,
        reload,
        method,
        onSaved,
        org,
      }}
    />
  );
}

function ActionFields({
  name,
  path,
  specs,
  initial,
  etag,
  reload,
  method,
  onSaved,
  org,
}: {
  name: string;
  path: string;
  specs: FieldSpec[];
  initial: Values;
  etag?: string;
  reload: () => Promise<void>;
  method: string;
  onSaved?: (result: unknown) => void;
  org: string;
}) {
  const action = useOperationalMutation(org, reload);
  const [values, setValues] = useState(initial);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const result = await action.run(path, values, etag, method);
        if (result) onSaved?.(result);
      }}
    >
      <Fields
        specs={specs}
        values={values}
        onChange={setValues}
        errors={action.error?.fields}
      />
      {action.error && (
        <p role="alert" className="text-sm text-red-800">
          {action.error.code}: {action.error.message}
        </p>
      )}
      {action.saved && (
        <p role="status" className="text-sm text-accent">
          {action.saved}
        </p>
      )}
      <Button disabled={action.pending}>
        <Check className="size-4" />
        {name}
      </Button>
    </form>
  );
}
export const reason: FieldSpec[] = [
  {
    path: "reason",
    label: "Reason",
    kind: "textarea",
    required: true,
    maxLength: 1000,
  },
];

function FactValue({ value, field }: { value: unknown; field: string }) {
  if (value === null || value === undefined) return <>Unknown</>;
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (Array.isArray(value))
    return (
      <ul className="space-y-1">
        {value.map((entry, index) => (
          <li key={index}>
            <FactValue value={entry} field={field} />
          </li>
        ))}
      </ul>
    );
  if (typeof value === "object") {
    const facts = value as Values;
    if (typeof facts.address_line1 === "string")
      return (
        <div className="space-y-1">
          <p>
            {[facts.address_line1, facts.address_line2]
              .filter(Boolean)
              .join(", ")}
          </p>
          <p>
            {[facts.locality, facts.city, facts.district, facts.postal_code]
              .filter(Boolean)
              .join(", ")}
          </p>
          <p>
            {facts.country_code === "IN" ? "India" : String(facts.country_code)}{" "}
            / State {String(facts.state_code)}
          </p>
          {facts.contact_name ? <p>{String(facts.contact_name)}</p> : null}
          {facts.contact_phone_e164 ? (
            <p>{String(facts.contact_phone_e164)}</p>
          ) : null}
          {facts.timezone ? (
            <p className="text-xs text-secondary">{String(facts.timezone)}</p>
          ) : null}
        </div>
      );
    return (
      <div className="space-y-1 border-l border-line pl-3">
        {Object.entries(facts).map(([key, entry]) => (
          <div key={key}>
            <span className="font-normal text-secondary">{title(key)}: </span>
            <FactValue value={entry} field={key} />
          </div>
        ))}
      </div>
    );
  }
  if (
    typeof value === "string" &&
    (field.endsWith("_at") || field.startsWith("planned_pickup_")) &&
    /^\d{4}-\d{2}-\d{2}T/.test(value)
  )
    return <>{displayTime(value)} IST</>;
  return <>{String(value)}</>;
}

export function Facts({ values }: { values: Values }) {
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2">
      {Object.entries(values).map(([key, value]) => (
        <div key={key} className="min-w-0">
          <dt className="text-secondary">{title(key)}</dt>
          <dd className="break-words font-medium">
            <FactValue value={value} field={key} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function ConsignmentHeader({ cn }: { cn: Consignment }) {
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">{cn.reference}</h2>
        <Mode mode={cn.execution_mode} />
      </div>
      <nav className="flex flex-wrap gap-4 text-sm text-accent">
        <Link href={`/shipments/trades/${cn.trade_id}/operations`}>
          Trade operations
        </Link>
        <Link href={`/shipments/consignments/${cn.id}/assignment`}>
          Assignment
        </Link>
        {cn.receipts && (
          <>
            <Link href={`/shipments/consignments/${cn.id}/receipt`}>
              Receipt
            </Link>
            <Link href={`/shipments/consignments/${cn.id}/inspection`}>
              Inspection
            </Link>
          </>
        )}
      </nav>
      <Facts
        values={{
          preparation: cn.planning_status,
          movement: cn.movement_status,
          revision_alignment: cn.revision_alignment,
          dispatch_readiness: cn.dispatch_readiness ?? "NOT_ASSESSED",
        }}
      />
    </>
  );
}
export function MovementTimeline({ cn }: { cn: Consignment }) {
  return (
    <ol className="space-y-3 border-l border-line pl-4">
      {cn.events.map((event) => (
        <li key={event.id} className="text-sm">
          <strong>{title(event.event_type)}</strong>
          <span className="ml-3 text-secondary">
            {displayTime(event.occurred_at)}
          </span>
          {event.notes && <p>{event.notes}</p>}
          {!event.projection_applied && (
            <p className="text-secondary">
              Historical observation; current projection unchanged.
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
