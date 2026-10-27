"use client";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Plus, Save, Send, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getValue, type Values } from "@/lib/trades";
import { newLine } from "@/lib/trade-draft";
import { useCommercialDraft } from "@/hooks/use-commercial-draft";
import {
  commercialSpecs,
  deliverySpecs,
  goodsSpecs,
  Milestones,
} from "./wizard-fields";
import { AgreementView } from "./agreement-view";
import { AddressFields, Fields } from "./fields";
import { useTradeContext } from "./trade-context";

const steps = [
  "Scope",
  "Parties",
  "Goods",
  "Commercial terms",
  "Delivery requirements",
  "Review",
  "Publish offer",
];
export function TradeWizard({ tradeId }: { tradeId?: string }) {
  const { org, role: interfaceRole, refs } = useTradeContext();
  const {
    role,
    step,
    setStep,
    trade,
    facts,
    change,
    saveState,
    errors,
    error,
    conflict,
    profile,
    partners,
    query,
    setQuery,
    pending,
    save,
    next,
    publish,
    choosePartner,
  } = useCommercialDraft(tradeId, org, interfaceRole);
  if (!org)
    return (
      <p>
        Select or{" "}
        <Link className="text-accent underline" href="/trades/organization">
          create an organisation
        </Link>{" "}
        before drafting a trade.
      </p>
    );
  if (tradeId && !trade)
    return (
      <div>
        {error ? (
          <p role="alert" className="text-red-800">
            {error}
          </p>
        ) : (
          <p role="status">Loading the saved candidate revision...</p>
        )}
      </div>
    );
  const items = (facts.items ?? []) as Values[];
  const other = role === "SELLER" ? "buyer" : "seller";
  const counterpart = partners.find(
    (item) => item.organization_id === facts[`${other}_organization_id`],
  );
  const memberCanEdit =
    !trade ||
    trade.next_actions.some((action) =>
      ["EDIT_DRAFT", "EDIT_AMENDMENT"].includes(action),
    );
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold">
          {trade?.pending_amendment ? "Prepare amendment" : "Create trade"}
        </h2>
        <p role="status" className="text-sm">
          {saveState}
          {trade ? ` | Revision ${trade.revision_number}` : ""}
        </p>
      </div>
      <div className="border-y border-line py-3 text-sm">
        <strong>
          Commercial agreement status: {trade?.agreement_status ?? "DRAFT"}
        </strong>
        <span className="ml-4 text-secondary">
          Dispatch readiness: Not assessed
        </span>
      </div>
      <nav aria-label="Create trade steps" className="flex flex-wrap gap-2">
        {steps.map((label, index) => (
          <button
            key={label}
            onClick={() => setStep(index)}
            aria-current={step === index ? "step" : undefined}
            className={`min-h-10 rounded border px-3 text-sm ${step === index ? "border-accent bg-accent text-white" : "border-line bg-surface"}`}
          >
            {index + 1}. {label}
          </button>
        ))}
      </nav>
      {error ? (
        <div
          role="alert"
          className="border-l-4 border-red-700 bg-red-50 p-4 text-sm text-red-800"
        >
          {error}
          {conflict ? (
            <button
              type="button"
              className="ml-3 underline"
              onClick={() => {
                if (
                  window.confirm(
                    "Reloading discards your unsaved local changes. Continue?",
                  )
                )
                  window.location.assign(
                    `/trades/${tradeId ?? trade?.trade_id}/edit`,
                  );
              }}
            >
              Reload current revision
            </button>
          ) : null}
        </div>
      ) : null}
      {!memberCanEdit ? (
        <p role="alert">
          This is not an editable proposal for your organisation.{" "}
          <Link href={`/trades/${trade?.trade_id}`} className="underline">
            Review offered terms
          </Link>
        </p>
      ) : (
        <div className="space-y-6">
          {step === 0 ? (
            <>
              <h3 className="font-semibold">Domestic interstate sale</h3>
              <p className="text-sm text-secondary">
                Seller and Buyer | Goods | INR | Road delivery
              </p>
              <Fields
                values={facts}
                onChange={change}
                errors={errors}
                specs={[
                  {
                    path: "purchase_order_reference",
                    label: "Purchase order reference",
                    maxLength: 100,
                  },
                ]}
              />
            </>
          ) : null}
          {step === 1 ? (
            <>
              <h3 className="font-semibold">Parties and billing</h3>
              <p className="text-sm text-secondary">
                Your party:{" "}
                {String(profile?.legal_name ?? "Loading business profile")} (
                {role.toLowerCase()}). Own billing details are snapshotted from
                your business profile.
              </p>
              <label className="block text-sm font-medium">
                Search trading partners
                <input
                  className="mt-1 block w-full rounded border p-2"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <label className="block text-sm font-medium">
                {role === "SELLER" ? "Buyer" : "Seller"} organisation
                <select
                  aria-label={
                    role === "SELLER"
                      ? "Buyer organisation"
                      : "Seller organisation"
                  }
                  className="mt-1 block w-full rounded border p-2"
                  value={String(facts[`${other}_organization_id`] ?? "")}
                  onChange={(event) => choosePartner(event.target.value)}
                >
                  <option value="">Unresolved (draft only)</option>
                  {!counterpart && facts[`${other}_organization_id`] ? (
                    <option value={String(facts[`${other}_organization_id`])}>
                      Selected counterparty
                    </option>
                  ) : null}
                  {partners.map((item) => (
                    <option
                      key={item.organization_id}
                      value={item.organization_id}
                    >
                      {item.legal_name}
                    </option>
                  ))}
                </select>
              </label>
              <Fields
                values={facts}
                onChange={change}
                errors={errors}
                specs={[
                  {
                    path: `${role.toLowerCase()}_registration_id`,
                    label: "Your declared registration",
                    kind: "select",
                    options: Object.fromEntries(
                      (profile?.registrations ?? []).map((item) => [
                        item.id,
                        `${item.gstin} (${item.verification_status})`,
                      ]),
                    ),
                  },
                  {
                    path: `${other}_registration_id`,
                    label: "Counterparty declared registration",
                    kind: "select",
                    options: Object.fromEntries(
                      (counterpart?.registrations ?? []).map((item) => [
                        item.id,
                        item.gstin,
                      ]),
                    ),
                  },
                  {
                    path: "transaction_layout",
                    label: "Transaction layout",
                    kind: "select",
                    options: [
                      "REGULAR",
                      "BILL_TO_SHIP_TO",
                      "BILL_FROM_DISPATCH_FROM",
                      "COMBINATION",
                    ],
                    required: true,
                  },
                ]}
              />
              <h4 className="font-semibold">
                Proposed counterparty billing address
              </h4>
              <AddressFields
                prefix={
                  other === "buyer"
                    ? "bill_to.billing_address"
                    : "bill_from.billing_address"
                }
                values={facts}
                onChange={change}
                errors={errors}
              />
              <p className="text-xs text-secondary">
                The other party reviews this proposed address before accepting
                the revision.
              </p>
            </>
          ) : null}
          {step === 2 ? (
            <>
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">Goods lines</h3>
                <Button
                  variant="outline"
                  onClick={() =>
                    change({ ...facts, items: [...items, newLine()] })
                  }
                  disabled={items.length >= 100}
                >
                  <Plus className="size-4" />
                  Add goods line
                </Button>
              </div>
              {items.map((item, index) => (
                <section
                  key={String(item.line_ref ?? index)}
                  className="space-y-4 border-t border-line pt-4"
                >
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold">Line {index + 1}</h4>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove goods line ${index + 1}`}
                      title="Remove goods line"
                      onClick={() =>
                        change({
                          ...facts,
                          items: items.filter(
                            (_, current) => current !== index,
                          ),
                        })
                      }
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                  <Fields
                    values={item}
                    onChange={(value) =>
                      change({
                        ...facts,
                        items: items.map((row, current) =>
                          current === index ? value : row,
                        ),
                      })
                    }
                    errors={errors
                      .filter((error) =>
                        error.path.startsWith(`items.${index}.`),
                      )
                      .map((error) => ({
                        ...error,
                        path: error.path.replace(`items.${index}.`, ""),
                      }))}
                    specs={goodsSpecs(refs.unit_codes)}
                  />
                </section>
              ))}
            </>
          ) : null}
          {step === 3 ? (
            <>
              <h3 className="font-semibold">Price and commercial terms</h3>
              <Fields
                values={facts}
                onChange={change}
                errors={errors}
                specs={commercialSpecs}
              />
              {getValue(facts, "commercial_terms.payment_mode") ===
              "MILESTONE" ? (
                <Milestones facts={facts} change={change} errors={errors} />
              ) : null}
            </>
          ) : null}
          {step === 4 ? (
            <>
              <h3 className="font-semibold">Dispatch address</h3>
              <AddressFields
                prefix="dispatch_from"
                operational
                values={facts}
                onChange={change}
                errors={errors}
              />
              <h3 className="font-semibold">Delivery address</h3>
              <AddressFields
                prefix="ship_to"
                operational
                values={facts}
                onChange={change}
                errors={errors}
              />
              <h3 className="font-semibold">
                Road delivery requirements (Asia/Kolkata)
              </h3>
              <Fields
                values={facts}
                onChange={change}
                errors={errors}
                specs={deliverySpecs}
              />
            </>
          ) : null}
          {step >= 5 ? (
            <>
              {trade?.current_candidate_revision ? (
                <AgreementView
                  title="Candidate commercial terms"
                  revision={trade.current_candidate_revision}
                />
              ) : (
                <p>Save the draft to preview server-calculated prices.</p>
              )}
              {errors.length ? (
                <div className="space-y-2">
                  <h3 className="font-semibold">Required before publication</h3>
                  <ul className="space-y-1 text-sm text-red-800">
                    {errors.map((item, index) => (
                      <li key={`${item.path}-${index}`}>
                        <strong>{item.path}:</strong> {item.message}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : null}
          {step === 6 ? (
            <div className="space-y-4">
              <p className="text-sm text-secondary">
                Publishing locks these terms. Both authorised parties must then
                approve the same revision.
              </p>
              <Button
                onClick={() => void publish()}
                disabled={pending || conflict}
              >
                <Send className="size-4" />
                Publish offer
              </Button>
            </div>
          ) : null}
          <div className="flex flex-wrap justify-between gap-3 border-t border-line pt-5">
            <Button
              variant="outline"
              disabled={step === 0 || pending}
              onClick={() => setStep((value) => value - 1)}
            >
              <ArrowLeft className="size-4" />
              Back
            </Button>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={pending || conflict}
                onClick={() => void save()}
              >
                <Save className="size-4" />
                Save draft
              </Button>
              {step < 6 ? (
                <Button
                  disabled={pending || conflict}
                  onClick={() => void next()}
                >
                  Save and continue
                  <ArrowRight className="size-4" />
                </Button>
              ) : null}
              {trade ? (
                <Button variant="outline" asChild>
                  <Link href={`/trades/${trade.trade_id}`}>Workspace</Link>
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
