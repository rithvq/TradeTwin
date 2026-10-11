"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Fields } from "@/components/trades/fields";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import {
  netReversible,
  TRIGGERS,
  type Candidate,
  type Payment,
  type Settlement,
} from "@/lib/operations";
import { displayMoney, type Values } from "@/lib/trades";
import { ActionForm, Facts, Mode, Refresh, Section, reason } from "./shared";

export function PaymentDesk({ tradeId }: { tradeId: string }) {
  const { org, me } = useTradeContext();
  const resource = useOperationsResource<Settlement>(
    `/trades/${tradeId}/settlement`,
    org,
  );
  const data = resource.data;
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!data) return <p role="status">Loading commercial payment desk...</p>;
  const member = me.memberships.find((m) => m.organization_id === org);
  const buyer = data.allowed_actions.includes("payment.report");
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">
            Commercial goods payment schedule
          </h2>
          <p className="text-sm text-secondary">
            {member?.legal_name} / {buyer ? "Buyer finance" : "Seller finance"}
          </p>
        </div>
        <div className="flex gap-3">
          <Mode mode={data.execution_mode} />
          <Refresh reload={resource.reload} />
        </div>
      </header>
      <Link
        className="text-accent underline"
        href={`/shipments/trades/${tradeId}/operations`}
      >
        Trade operations
      </Link>
      <Facts
        values={{
          pricing_basis: data.pricing_basis,
          accepted_quoted_goods_amount: displayMoney(
            data.accepted_quoted_goods_total_minor,
          ),
          schedule_status: data.schedule_status,
          reported: displayMoney(data.reported_payment_minor),
          acknowledged: displayMoney(data.acknowledged_payment_minor),
          allocated: displayMoney(data.net_allocated_minor),
          unallocated_acknowledged: displayMoney(
            data.unallocated_acknowledged_minor,
          ),
          outstanding: displayMoney(data.outstanding_scheduled_minor),
          overapplied: displayMoney(data.overapplied_minor),
          provider_verification: "Not assessed",
          final_invoice_reconciliation: "Not assessed",
        }}
      />
      <p className="text-sm text-secondary">
        Additional tax/freight and final invoice reconciliation: not assessed.
        Manual reports are not bank-verified payments.
      </p>
      {data.schedule_review_required && (
        <p
          role="alert"
          className="border-l-4 border-amber-500 bg-amber-50 p-3 text-sm text-amber-900"
        >
          Payment schedule requires bilateral review. Existing reports and
          allocations are preserved.
        </p>
      )}
      <Section name="Goods obligations">
        {data.obligations.map((o) => (
          <article key={o.obligation_ref} className="border-b py-3">
            <strong>{o.label}</strong>
            <Facts
              values={{
                face_amount: displayMoney(o.face_amount_minor),
                trigger: o.trigger,
                trigger_met: o.trigger_met,
                due_on: o.due_on,
                allocated: displayMoney(o.net_allocated_minor),
                remaining: displayMoney(o.remaining_minor),
                overapplied: displayMoney(o.overapplied_minor),
                status: o.status,
              }}
            />
          </article>
        ))}
      </Section>
      {data.allowed_actions.includes("payment_schedule.propose") && (
        <Section name="Propose agreed schedule">
          <ScheduleEditor
            tradeId={tradeId}
            data={data}
            reload={resource.reload}
          />
        </Section>
      )}
      <Section name="Schedule approvals and history">
        {data.schedules.map((s) => (
          <article key={s.id} className="space-y-3 border-b py-4">
            <Facts
              values={{
                schedule: s.id,
                status: s.status,
                accepted_revision: s.accepted_revision_id,
                content_hash: s.content_hash,
              }}
            />
            {s.lines.map((l) => (
              <p className="text-sm" key={l.id}>
                {l.label}: {displayMoney(l.face_amount_minor)} / {l.trigger}
              </p>
            ))}
            {s.approvals.map((a) => (
              <p className="break-all text-xs" key={a.id}>
                {a.organization_id}: {a.decision}
              </p>
            ))}
            {s.status === "PROPOSED" &&
              data.allowed_actions.includes("payment_schedule.approve") &&
              !s.approvals.some((a) => a.organization_id === org) && (
                <>
                  <ActionForm
                    name="Approve exact schedule"
                    path={`/payment-schedules/${s.id}/approvals`}
                    initial={{
                      decision: "ACCEPT",
                      content_hash: s.content_hash,
                    }}
                    reload={resource.reload}
                  />
                  <details>
                    <summary className="cursor-pointer text-sm">
                      Reject schedule
                    </summary>
                    <ActionForm
                      name="Reject schedule"
                      path={`/payment-schedules/${s.id}/approvals`}
                      initial={{
                        decision: "REJECT",
                        content_hash: s.content_hash,
                      }}
                      specs={reason}
                      reload={resource.reload}
                    />
                  </details>
                </>
              )}
          </article>
        ))}
      </Section>
      {buyer && (
        <Section name="Report outgoing payment">
          <ActionForm
            name="Report manual payment"
            path={`/trades/${tradeId}/payments`}
            initial={{
              paid_on: new Date().toISOString().slice(0, 10),
              method: "BANK_TRANSFER",
            }}
            specs={[
              {
                path: "amount_minor",
                label: "Payment amount (paise)",
                required: true,
              },
              {
                path: "paid_on",
                label: "Paid on",
                kind: "date",
                required: true,
              },
              {
                path: "method",
                label: "Payment method",
                kind: "select",
                options: ["BANK_TRANSFER", "UPI", "CASH", "CHEQUE", "OTHER"],
                required: true,
              },
              {
                path: "declared_reference",
                label: "Declared transaction reference",
              },
              { path: "notes", label: "Payment notes", kind: "textarea" },
            ]}
            reload={resource.reload}
          />
        </Section>
      )}
      <Section name="Payment reports">
        {data.payments.map((p) => (
          <PaymentCard
            key={p.id}
            payment={p}
            data={data}
            reload={resource.reload}
          />
        ))}
      </Section>
    </div>
  );
}

function ScheduleEditor({
  tradeId,
  data,
  reload,
}: {
  tradeId: string;
  data: Settlement;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const candidate = useOperationsResource<Candidate>(
    `/trades/${tradeId}/payment-schedule-candidate`,
    org,
  );
  const trade = useOperationsResource<{ etag: string }>(
    `/trades/${tradeId}`,
    org,
  );
  const action = useOperationalMutation(org, async () => {
    await reload();
    await trade.reload();
  });
  const [lines, setLines] = useState<Values[] | null>(null);
  const [values, setValues] = useState<Values>({
    due_timezone: "Asia/Kolkata",
  });
  useEffect(() => {
    setLines(null);
  }, [org, tradeId]);
  useEffect(() => {
    if (!candidate.data || lines) return;
    const active = data.schedules.find((s) => s.status === "ACTIVE");
    const defaults: Values[] = candidate.data.lines.map((l, i) => ({
      ...l,
      ...(active?.lines[i]
        ? { obligation_ref: active.lines[i].obligation_ref }
        : {}),
    }));
    const funded = data.obligations.filter(
      (o) => BigInt(o.net_allocated_minor ?? "0") > BigInt(0),
    );
    for (const o of funded)
      if (!defaults.some((l) => l.obligation_ref === o.obligation_ref))
        defaults.push({
          obligation_ref: o.obligation_ref,
          label: o.label,
          face_amount_minor: "0",
          trigger: o.trigger,
          offset_days: o.offset_days,
          fixed_due_on: o.fixed_due_on,
        });
    setLines(defaults);
  }, [candidate.data, data, lines]);
  if (!candidate.data || !lines)
    return <p>{candidate.error || "Loading schedule candidate..."}</p>;
  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        await action.run(
          `/trades/${tradeId}/payment-schedules`,
          {
            accepted_revision_id: candidate.data!.accepted_revision_id,
            ...values,
            lines: lines.map((l) => ({
              ...l,
              fixed_due_on: l.trigger === "FIXED_DATE" ? l.fixed_due_on : null,
            })),
          },
          trade.data?.etag,
        );
      }}
    >
      {candidate.data.questions.map((q) => (
        <p className="text-sm text-amber-900" key={q}>
          {q}
        </p>
      ))}
      <Fields
        specs={[
          {
            path: "reason",
            label: "Clarification or replacement reason",
            kind: "textarea",
            maxLength: 1000,
          },
          { path: "due_timezone", label: "Due timezone", required: true },
        ]}
        values={values}
        onChange={setValues}
        errors={action.error?.fields}
      />
      {lines.map((line, index) => (
        <fieldset key={index} className="space-y-3 border-t py-3">
          <legend className="text-sm font-semibold">
            Obligation {index + 1}
          </legend>
          <Fields
            specs={[
              {
                path: "label",
                label: "Obligation label",
                required: true,
                maxLength: 100,
              },
              {
                path: "face_amount_minor",
                label: "Face amount (paise)",
                required: true,
              },
              {
                path: "trigger",
                label: "Full-trade trigger",
                kind: "select",
                options: TRIGGERS,
                required: true,
              },
              { path: "offset_days", label: "Offset days", kind: "integer" },
              ...(line.trigger === "FIXED_DATE"
                ? [
                    {
                      path: "fixed_due_on",
                      label: "Fixed due date",
                      kind: "date" as const,
                      required: true,
                    },
                  ]
                : []),
            ]}
            values={line}
            onChange={(value) =>
              setLines(lines.map((l, i) => (i === index ? value : l)))
            }
            errors={action.error?.fields}
          />
          {Boolean(line.obligation_ref) && (
            <p className="break-all text-xs text-secondary">
              Retained obligation: {String(line.obligation_ref)}
            </p>
          )}
          <Button
            type="button"
            variant="outline"
            size="icon"
            title="Remove unfunded obligation"
            aria-label={`Remove obligation ${index + 1}`}
            onClick={() => setLines(lines.filter((_, i) => i !== index))}
          >
            <Trash2 className="size-4" />
          </Button>
        </fieldset>
      ))}
      <Button
        type="button"
        variant="outline"
        onClick={() =>
          setLines([
            ...lines,
            {
              label: "Goods obligation",
              face_amount_minor: "0",
              trigger: "FULL_DELIVERY",
              offset_days: 0,
              fixed_due_on: null,
            },
          ])
        }
      >
        <Plus className="size-4" />
        Add obligation
      </Button>
      {action.error && (
        <p role="alert" className="text-red-800">
          {action.error.code}: {action.error.message}
        </p>
      )}
      {action.saved && (
        <p role="status">Schedule proposed for separate finance approvals.</p>
      )}
      <div>
        <Button disabled={action.pending}>
          <Check className="size-4" />
          Propose goods schedule
        </Button>
      </div>
    </form>
  );
}

function PaymentCard({
  payment: p,
  data,
  reload,
}: {
  payment: Payment;
  data: Settlement;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const can = (permission: string) => data.allowed_actions.includes(permission);
  const active = !["VOID", "WITHDRAWN"].includes(p.status);
  return (
    <article className="space-y-4 border-b py-5">
      <Facts
        values={{
          payment: p.id,
          status: p.status,
          amount: displayMoney(p.amount_minor),
          paid_on: p.paid_on,
          method: p.method,
          transaction_reference: p.declared_reference,
          allocated: displayMoney(p.net_allocated_minor),
          provider_verification: "Not assessed",
        }}
      />
      {active &&
        can("payment.acknowledge") &&
        p.status !== "COUNTERPARTY_ACKNOWLEDGED" && (
          <ActionForm
            name="Acknowledge reported payment"
            path={`/payments/${p.id}/acknowledgements`}
            specs={[
              {
                path: "notes",
                label: "Acknowledgment notes",
                kind: "textarea",
              },
            ]}
            reload={reload}
          />
        )}
      {active && can("payment.acknowledge") && (
        <details>
          <summary className="cursor-pointer text-sm text-red-800">
            Dispute payment report
          </summary>
          <ActionForm
            name="Dispute payment"
            path={`/payments/${p.id}/disputes`}
            specs={reason}
            reload={reload}
          />
        </details>
      )}
      {p.status === "MANUAL_REPORTED" && can("payment.report") && (
        <details>
          <summary className="cursor-pointer text-sm">
            Withdraw unacknowledged report
          </summary>
          <ActionForm
            name="Withdraw report"
            path={`/payments/${p.id}/withdrawals`}
            specs={reason}
            reload={reload}
          />
        </details>
      )}
      {p.status === "COUNTERPARTY_ACKNOWLEDGED" &&
        can("payment.allocate") &&
        !data.schedule_review_required &&
        data.active_schedule_id && (
          <ActionForm
            name="Allocate acknowledged funds"
            path={`/payments/${p.id}/allocations`}
            initial={{
              allocations: [
                {
                  obligation_ref: data.obligations[0]?.obligation_ref,
                  amount_minor: "",
                },
              ],
            }}
            specs={[
              {
                path: "allocations.0.obligation_ref",
                label: "Approved goods obligation",
                kind: "select",
                options: Object.fromEntries(
                  data.obligations.map((o) => [
                    o.obligation_ref,
                    `${o.label}: ${displayMoney(o.remaining_minor)} remaining`,
                  ]),
                ),
                required: true,
              },
              {
                path: "allocations.0.amount_minor",
                label: "Allocation amount (paise)",
                required: true,
              },
            ]}
            reload={reload}
          />
        )}
      {p.allocations.map((a) => (
        <div key={a.id} className="space-y-2 border-t pt-3">
          <p className="text-sm">
            {a.entry_type}: {displayMoney(a.amount_minor)}
          </p>
          <p className="break-all text-xs text-secondary">
            Obligation: {a.obligation_ref}
          </p>
          {a.entry_type === "ALLOCATION" &&
            netReversible(p, a.id) !== "0" &&
            can("payment.allocation.reverse") && (
              <details>
                <summary className="cursor-pointer text-sm">
                  Reverse allocation
                </summary>
                <ActionForm
                  name="Record allocation reversal"
                  path={`/payment-allocations/${a.id}/reversals`}
                  specs={[
                    {
                      path: "amount_minor",
                      label: "Reversal amount (paise)",
                      required: true,
                    },
                    ...reason,
                  ]}
                  reload={reload}
                />
              </details>
            )}
        </div>
      ))}
      {active && can("payment.void.propose") && !p.pending_void_request && (
        <details>
          <summary className="cursor-pointer text-sm">
            Request bilateral record void
          </summary>
          <ActionForm
            name="Request record void"
            path={`/payments/${p.id}/void-requests`}
            specs={reason}
            reload={reload}
          />
        </details>
      )}
      {p.pending_void_request &&
        p.pending_void_request.actor_organization_id !== org &&
        can("payment.void.approve") && (
          <>
            <ActionForm
              name="Approve record void (no refund)"
              path={`/payments/${p.id}/void-decisions`}
              initial={{
                void_request_id: p.pending_void_request.id,
                decision: "APPROVE",
              }}
              reload={reload}
            />
            <ActionForm
              name="Reject record void"
              path={`/payments/${p.id}/void-decisions`}
              initial={{
                void_request_id: p.pending_void_request.id,
                decision: "REJECT",
              }}
              specs={reason}
              reload={reload}
            />
          </>
        )}
      {p.decisions.map((d) => (
        <p className="text-xs text-secondary" key={d.id}>
          {d.decision}: {d.reason}
        </p>
      ))}
    </article>
  );
}
