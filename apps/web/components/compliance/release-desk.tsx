"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Play,
  ShieldCheck,
  FileDown,
  RefreshCw,
  PackageCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import {
  ActionForm,
  Facts,
  Mode,
  Section,
  reason,
} from "@/components/operations/shared";
import { Status } from "@/components/document-desk/shared";
import type { Consignment } from "@/lib/operations";
import type {
  ComplianceContext,
  DispatchAction,
  Evaluation,
  Readiness,
} from "@/lib/guarded-dispatch";
import { beforeExpiry } from "@/lib/guarded-dispatch";
import { displayTime, type Values } from "@/lib/trades";
import { PrepareFacts, LoadingManifest } from "./prepare-facts";
import { EvidenceBindings } from "./evidence-bindings";
import { PrivateTurnover } from "./private-turnover";
import { TransportEvidenceDesk } from "./transport-evidence";
import {
  ComplianceEvidenceGraph,
  type EvidenceGraphData,
} from "./evidence-graph";

export function ReleaseDesk({
  cn,
  module = "Compliance",
}: {
  cn: Consignment;
  module?: string;
}) {
  const { org, me } = useTradeContext();
  const context = useOperationsResource<ComplianceContext>(
    `/consignments/${cn.id}/compliance-context`,
    org,
  );
  const [action, setAction] = useState<DispatchAction>(
    cn.movement_status === "PICKED_UP" ? "DEPARTED" : "PICKUP_CONFIRMED",
  );
  const readiness = useOperationsResource<Readiness>(
    `/consignments/${cn.id}/dispatch-readiness?action=${action}`,
    org,
  );
  const refresh = async () => {
    await context.reload();
    await readiness.reload();
  };
  const mutation = useOperationalMutation(org, refresh);
  const reloadReadiness = readiness.reload;
  useEffect(() => {
    const timer = window.setInterval(
      () => void reloadReadiness(),
      readiness.data?.evaluation?.job_state === "QUEUED" ? 2000 : 10000,
    );
    return () => window.clearInterval(timer);
  }, [reloadReadiness, readiness.data?.evaluation?.job_state]);
  if (context.error) return <p role="alert">{context.error}</p>;
  if (!context.data) return <p role="status">Loading compliance context...</p>;
  const data = context.data,
    state = readiness.data,
    evaluation = state?.evaluation;
  const can = (permission: string) => data.capabilities.includes(permission);
  if (module === "Optimizer")
    return <ConstraintView id={cn.id} action={action} />;
  if (module === "Evidence" && evaluation)
    return <EvidenceView evaluation={evaluation} />;
  if (module === "Graph" && evaluation)
    return <EvidenceView evaluation={evaluation} compact />;
  if (module === "Risk")
    return (
      <Section name={`${cn.reference}: dispatch blockers`}>
        <Status value={state?.state ?? "NOT_ASSESSED"} />
        {state?.operational_alerts?.map((alert) => (
          <article key={alert.code} className="border-b py-3">
            <strong>{alert.code}</strong>
            <Status value={alert.severity} />
            <p className="text-sm">{alert.explanation}</p>
          </article>
        ))}
        {evaluation?.requirements
          .filter((r) => r.outcome === "FAILED" || r.outcome === "UNKNOWN")
          .map((r) => (
            <article key={r.id} className="border-b py-3">
              <strong>{r.requirement_code}</strong>
              <p className="text-sm">{r.explanation}</p>
              <Status value={r.outcome} />
            </article>
          ))}
      </Section>
    );
  return (
    <article className="border-t border-line py-5 space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{cn.reference}</h3>
          <p className="text-sm text-secondary">
            Platform dispatch authorisation
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Mode mode={cn.execution_mode} />
          <Status value={state?.state ?? "NOT_ASSESSED"} />
          <Button
            size="icon"
            variant="outline"
            title="Refresh compliance"
            aria-label="Refresh compliance"
            onClick={() => void refresh()}
          >
            <RefreshCw className="size-4" />
          </Button>
        </div>
      </header>
      {state?.historical_notice && (
        <p className="text-sm text-amber-900">{state.historical_notice}</p>
      )}
      {can("compliance.recipient.confirm") && (
        <Section name="Recipient identity and delivery confirmation">
          <Facts values={data.recipient_baseline} />
          {data.recipient_confirmation && (
            <Facts values={data.recipient_confirmation} />
          )}
          <ActionForm
            name="Record recipient confirmation"
            path={`/consignments/${cn.id}/recipient-confirmations`}
            etag={data.etag}
            key={data.context_version}
            initial={{
              ...data.recipient_baseline,
              expected_context_version: data.context_version,
              confirmation: "MATCHES_ACCEPTED_SNAPSHOT",
              recipient_category_code: "REGISTERED_REGULAR",
            }}
            specs={[
              {
                path: "confirmation",
                label: "Recipient position",
                kind: "select",
                options: ["MATCHES_ACCEPTED_SNAPSHOT", "REQUEST_CORRECTION"],
              },
              { path: "gstin", label: "Your GSTIN", required: true },
              {
                path: "address_line1",
                label: "Delivery address line",
                required: true,
              },
              {
                path: "destination_state_code",
                label: "Destination state code",
                required: true,
              },
              {
                path: "recipient_category_code",
                label: "Recipient category",
                kind: "select",
                options: ["REGISTERED_REGULAR", "SEZ", "UNKNOWN"],
              },
              {
                path: "note",
                label: "Confirmation / correction note",
                kind: "textarea",
                required: true,
              },
            ]}
            reload={refresh}
          />
        </Section>
      )}
      <div className="flex gap-1" role="group" aria-label="Dispatch action">
        {(["PICKUP_CONFIRMED", "DEPARTED"] as DispatchAction[]).map((a) => (
          <button
            key={a}
            className={`border px-4 py-2 text-sm ${action === a ? "bg-accent text-white" : ""}`}
            aria-pressed={action === a}
            onClick={() => setAction(a)}
          >
            {a === "PICKUP_CONFIRMED" ? "Pickup" : "Departure"}
          </button>
        ))}
      </div>
      {can("compliance.facts.prepare") && (
        <details>
          <summary className="cursor-pointer font-semibold">
            Prepare facts, manifest and evidence
          </summary>
          <PrepareFacts
            key={(data.heads.current_fact_revision_id as string) ?? "draft"}
            data={data}
            cn={cn}
            reload={refresh}
          />
          <LoadingManifest data={data} cn={cn} reload={refresh} />
          <EvidenceBindings data={data} reload={refresh} />
        </details>
      )}
      {can("compliance.facts.review") && (
        <Section name="Independent declaration review">
          {data.fact_revisions
            .filter((f) => f.submitted_for_review)
            .map((f) => (
              <details key={f.id}>
                <summary className="cursor-pointer font-medium">
                  Declaration {f.id.slice(0, 8)}
                </summary>
                {f.facts && (
                  <Facts
                    values={Object.fromEntries(
                      Object.entries(f.facts).filter(
                        ([k]) => k !== "field_provenance",
                      ),
                    )}
                  />
                )}
                <Facts values={{ content_hash: f.content_hash }} />
                <DeclarationActions
                  revision={f.id}
                  preparedBy={f.prepared_by_user_id}
                  reload={refresh}
                />
              </details>
            ))}
        </Section>
      )}
      {can("turnover.read") && !can("compliance.facts.prepare") && (
        <PrivateTurnover data={data} reload={refresh} />
      )}
      {can("compliance.evaluate") && (
        <TransportEvidenceDesk data={data} cn={cn} reload={refresh} />
      )}
      {!can("compliance.evaluate") &&
        (can("transport.evidence.prepare") ||
          can("transport.evidence.review")) && (
          <TransportEvidenceDesk data={data} cn={cn} reload={refresh} />
        )}
      {can("compliance.evaluate") && (
        <Button
          disabled={mutation.pending || evaluation?.job_state === "QUEUED"}
          onClick={() =>
            void mutation.run(
              `/consignments/${cn.id}/compliance-evaluations`,
              { action, expected_context_version: data.context_version },
              data.etag,
            )
          }
        >
          <Play className="size-4" />
          Evaluate {action === "DEPARTED" ? "departure" : "pickup"}
        </Button>
      )}
      {mutation.error && (
        <p role="alert" className="text-sm text-red-800">
          {mutation.error.code}: {mutation.error.message}
        </p>
      )}
      {readiness.error && <p role="alert">{readiness.error}</p>}
      {evaluation && (
        <EvaluationView
          evaluation={evaluation}
          canReview={can("dispatch.release.approve")}
          reload={refresh}
        />
      )}
      {can("document.manual_observation.review") && (
        <Section name="Independent portal observation review">
          {data.documents.flatMap((doc) =>
            doc.manual_attestations.map((report) => (
              <article key={report.id} className="space-y-3 border-b py-3">
                <strong>
                  {doc.label} / {report.check_type}
                </strong>
                <Status value={report.review_outcome} />
                {report.reported_by_user_id === me.user.id ? (
                  <p className="text-sm text-amber-900">
                    A different reviewer is required.
                  </p>
                ) : (
                  <ActionForm
                    name="Review portal observation"
                    path={`/manual-portal-attestations/${report.id}/reviews`}
                    initial={{ decision: "APPROVE_DECLARATION" }}
                    specs={[
                      {
                        path: "decision",
                        label: "Decision",
                        kind: "select",
                        options: [
                          "APPROVE_DECLARATION",
                          "RETURN_FOR_CORRECTION",
                        ],
                      },
                      ...reason,
                    ]}
                    reload={refresh}
                  />
                )}
              </article>
            )),
          )}
        </Section>
      )}
      {evaluation &&
        ["ELIGIBLE_FOR_REVIEW", "NEEDS_REVIEW"].includes(
          evaluation.decision,
        ) && (
          <DispatchPreparation
            evaluation={evaluation}
            context={data}
            cn={cn}
            reload={refresh}
          />
        )}
      {evaluation && (
        <CaseDesk
          id={cn.id}
          currentEvaluation={evaluation}
          canResolve={can("compliance.case.resolve")}
          reload={refresh}
          canRespond={
            can("compliance.case.comment") || can("compliance.case.resolve")
          }
        />
      )}
      {evaluation && <EvaluationHistory id={cn.id} current={evaluation} />}
      {!!data.holds?.some((hold) => hold.active) && (
        <Section name="Active integrity holds">
          {data.holds
            ?.filter((h) => h.active)
            .map((hold) => (
              <article key={hold.id} className="border-b py-3 space-y-3">
                <strong>{hold.reason_code}</strong>
                <p className="text-sm">{hold.reason}</p>
                {can("compliance.hold.release.request") && (
                  <ActionForm
                    name="Request independent hold release"
                    path={`/compliance-holds/${hold.id}/release-requests`}
                    specs={reason}
                    reload={refresh}
                  />
                )}
                {hold.events.find(
                  (e) => e.event_type === "RELEASE_REQUESTED",
                ) &&
                  can("compliance.hold.release.approve") &&
                  hold.events.find((e) => e.event_type === "RELEASE_REQUESTED")!
                    .created_by_user_id !== me.user.id && (
                    <ActionForm
                      name="Approve hold release"
                      path={`/compliance-holds/${hold.id}/release-approvals`}
                      initial={{
                        release_request_event_id: hold.events.find(
                          (e) => e.event_type === "RELEASE_REQUESTED",
                        )!.id,
                      }}
                      specs={reason}
                      reload={refresh}
                    />
                  )}
              </article>
            ))}
        </Section>
      )}
      {can("compliance.hold.create") && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold text-red-800">
            Raise integrity hold
          </summary>
          <ActionForm
            name="Raise blocking hold"
            path={`/consignments/${cn.id}/compliance-holds`}
            specs={[
              {
                path: "reason_code",
                label: "Integrity reason",
                kind: "select",
                options: [
                  "SUSPECTED_TAMPERING",
                  "CONTRADICTORY_AUTHORITY_OBSERVATIONS",
                  "IDENTITY_MISMATCH",
                  "PUBLISHED_INTEGRITY_REASON",
                ],
              },
              ...reason,
            ]}
            reload={refresh}
          />
        </details>
      )}
    </article>
  );
}

function DeclarationActions({
  revision,
  preparedBy,
  reload,
}: {
  revision: string;
  preparedBy: string;
  reload: () => Promise<void>;
}) {
  const { me } = useTradeContext();
  if (me.user.id === preparedBy)
    return (
      <p className="text-sm text-amber-900">Independent reviewer required</p>
    );
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {["APPROVE_DECLARATION", "RETURN_FOR_CORRECTION"].map((decision) => (
        <ActionForm
          key={decision}
          name={
            decision === "APPROVE_DECLARATION"
              ? "Approve declaration"
              : "Return declaration"
          }
          path={`/compliance-fact-revisions/${revision}/reviews`}
          initial={{ decision }}
          specs={reason}
          reload={reload}
        />
      ))}
    </div>
  );
}

export function EvaluationView({
  evaluation: e,
  canReview = false,
  reload,
}: {
  evaluation: Evaluation;
  canReview?: boolean;
  reload: () => Promise<void>;
}) {
  const [warnings, setWarnings] = useState<string[]>([]);
  return (
    <Section name="Versioned requirements">
      <Facts
        values={{
          decision: e.decision,
          freshness: e.freshness,
          context_version: e.context_version,
          evaluation_hash: e.evaluation_hash,
          evaluated_at: displayTime(e.evaluated_at),
          valid_until: displayTime(e.valid_until),
          coverage: e.coverage,
        }}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr>
              {[
                "Requirement",
                "Class",
                "Applicability",
                "Outcome",
                "Why / corrective action",
              ].map((c) => (
                <th key={c} className="border-b p-2">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {e.requirements.map((r) => (
              <tr key={r.id}>
                <td className="border-b p-2 font-medium">
                  {r.requirement_code}
                </td>
                <td className="border-b p-2">{r.rule_class}</td>
                <td className="border-b p-2">{r.applicability}</td>
                <td className="border-b p-2">
                  <Status value={r.outcome} />
                </td>
                <td className="border-b p-2">
                  <p>{r.explanation}</p>
                  {r.observed_json.comparison && (
                    <Facts values={r.observed_json.comparison} />
                  )}
                  {r.outcome !== "SATISFIED" &&
                    r.outcome !== "NOT_APPLICABLE" &&
                    r.observed_json.correction_links?.map((link) => (
                      <Link
                        key={link.document_version_id}
                        className="mr-3 text-sm text-accent underline"
                        href={link.url}
                      >
                        Correct source {link.document_version_id.slice(0, 8)}
                      </Link>
                    ))}
                  <p className="mt-1 text-xs text-secondary">
                    {r.remedies_json.join(", ")}
                  </p>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {e.limitations.map((l, i) => (
        <p key={i} className="text-sm text-secondary">
          {l}
        </p>
      ))}
      {canReview &&
        !e.release_review_blockers.length &&
        e.freshness === "CURRENT" &&
        beforeExpiry(e.valid_until) &&
        ["ELIGIBLE_FOR_REVIEW", "NEEDS_REVIEW"].includes(e.decision) && (
          <div className="space-y-3">
            {!!e.warnings.length && (
              <fieldset className="space-y-2">
                <legend className="text-sm font-semibold">
                  Published policy warning acknowledgments
                </legend>
                {e.warning_acknowledgment_options.map((option) => (
                  <label
                    key={option.id}
                    className="flex items-start gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={warnings.includes(option.id)}
                      onChange={() =>
                        setWarnings(
                          warnings.includes(option.id)
                            ? warnings.filter((id) => id !== option.id)
                            : [...warnings, option.id],
                        )
                      }
                    />
                    {option.reason}
                  </label>
                ))}
              </fieldset>
            )}
            <ActionForm
              key={e.id + warnings.join(":")}
              name="Approve platform release"
              path={`/compliance-evaluations/${e.id}/review-decisions`}
              initial={{
                decision: "APPROVE_RELEASE",
                evaluation_hash: e.evaluation_hash,
                acknowledged_warning_action_ids: warnings,
              }}
              specs={reason}
              reload={reload}
            />
          </div>
        )}
      {canReview && (
        <p className="text-sm text-amber-900">
          {e.release_review_blockers.join(", ")}
        </p>
      )}
      {canReview &&
        !e.release_review_blockers.includes("SELF_REVIEW_NOT_ALLOWED") && (
          <ActionForm
            name="Return evaluation for correction"
            path={`/compliance-evaluations/${e.id}/review-decisions`}
            initial={{
              decision: "RETURN_FOR_CORRECTION",
              evaluation_hash: e.evaluation_hash,
            }}
            specs={reason}
            reload={reload}
          />
        )}
    </Section>
  );
}

function DispatchPreparation({
  evaluation: e,
  context: c,
  cn,
  reload,
}: {
  evaluation: Evaluation;
  context: ComplianceContext;
  cn: Consignment;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const mutation = useOperationalMutation(org, reload);
  const approval =
    e.release_reviews[0]?.decision === "APPROVE_RELEASE"
      ? e.release_reviews[0]
      : null;
  const packet = e.packets[0],
    acknowledgment = packet?.acknowledgments[0];
  const carry = e.requirements.find(
    (r) => r.requirement_code === "CARRIED_DOCUMENTS",
  );
  const current = e.freshness === "CURRENT" && beforeExpiry(e.valid_until);
  const sources = e.packet_source_options;
  const [selected, setSelected] = useState<Record<string, string>>({});
  return (
    <Section name="Dispatch packet">
      <Facts
        values={{
          approval: approval?.decision ?? "Independent approval required",
          packet: packet?.packet_hash ?? "Not prepared",
          driver_acknowledgment: acknowledgment ? "Recorded" : "Required",
          valid_until: e.valid_until,
        }}
      />
      {c.capabilities.includes("dispatch.packet.prepare") &&
        approval &&
        current && (
          <>
            <div className="space-y-3">
              {sources.map((d) => (
                <label
                  key={d.document_version_id}
                  className="block text-sm font-medium"
                >
                  {d.document_type} / {d.document_version_id.slice(0, 8)}
                  <select
                    className="mt-1 block w-full rounded border p-2"
                    value={selected[d.document_version_id] ?? ""}
                    onChange={(event) =>
                      setSelected({
                        ...selected,
                        [d.document_version_id]: event.target.value,
                      })
                    }
                  >
                    <option value="">Not selected</option>
                    <option
                      value={
                        d.document_type === "TAX_INVOICE"
                          ? "PAPER_INVOICE_REFERENCE"
                          : "EWB_NUMBER"
                      }
                    >
                      {d.document_type === "TAX_INVOICE"
                        ? "Paper invoice carried"
                        : "E-way bill number available"}
                    </option>
                    {d.assets.map((a) => (
                      <option key={a.attachment_id} value={a.attachment_id}>
                        Offline source copy
                      </option>
                    ))}
                    {d.signed_qr_artifact_ids.map((id) => (
                      <option key={id} value={`qr:${id}`}>
                        Verified signed QR image
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            <Button
              disabled={mutation.pending || !carry}
              onClick={() =>
                void mutation.run(`/consignments/${cn.id}/dispatch-packets`, {
                  action: e.action,
                  evaluation_id: e.id,
                  evaluation_hash: e.evaluation_hash,
                  approval_id: approval.id,
                  selected_representations: sources
                    .filter((d) => selected[d.document_version_id])
                    .map((d) => {
                      const choice = selected[d.document_version_id],
                        qr = choice.startsWith("qr:"),
                        reference = [
                          "PAPER_INVOICE_REFERENCE",
                          "EWB_NUMBER",
                        ].includes(choice);
                      return {
                        requirement_id: carry?.id,
                        representation_type: qr
                          ? "SIGNED_IRN_QR"
                          : reference
                            ? choice
                            : d.document_type === "TAX_INVOICE"
                              ? "INVOICE_COPY"
                              : "EWB_COPY",
                        source_reference: {
                          document_version_id: d.document_version_id,
                          ...(qr
                            ? { artifact_id: choice.slice(3) }
                            : reference
                              ? {}
                              : { attachment_id: choice }),
                        },
                        carry_method: qr
                          ? "SIGNED_IRN_QR_ELECTRONIC"
                          : choice === "PAPER_INVOICE_REFERENCE"
                            ? "PAPER_COPY"
                            : choice === "EWB_NUMBER"
                              ? "EWB_NUMBER_AVAILABLE"
                              : "DIGITAL_OFFLINE_COPY",
                      };
                    }),
                })
              }
            >
              <PackageCheck className="size-4" />
              Prepare exact dispatch packet
            </Button>
          </>
        )}
      {packet && (
        <Link
          href={`/shipments/consignments/${cn.id}/assignment`}
          className="text-sm text-accent underline"
        >
          Assigned-driver task
        </Link>
      )}
      {c.capabilities.includes("dispatch.authorisation.request") &&
        approval &&
        packet &&
        acknowledgment &&
        current && (
          <Button
            disabled={mutation.pending}
            onClick={() =>
              void mutation.run(
                `/consignments/${cn.id}/dispatch-authorizations`,
                {
                  action: e.action,
                  evaluation_id: e.id,
                  evaluation_hash: e.evaluation_hash,
                  approval_id: approval.id,
                  packet_id: packet.id,
                  packet_hash: packet.packet_hash,
                  acknowledgment_id: acknowledgment.id,
                  expected_context_version: c.context_version,
                },
                c.etag,
              )
            }
          >
            <ShieldCheck className="size-4" />
            Request platform dispatch authorisation
          </Button>
        )}
      {mutation.error && (
        <p role="alert">
          {mutation.error.code}: {mutation.error.message}
        </p>
      )}
    </Section>
  );
}

function CaseDesk({
  id,
  canRespond,
  canResolve,
  currentEvaluation,
  reload,
}: {
  id: string;
  canRespond: boolean;
  canResolve: boolean;
  currentEvaluation: Evaluation;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<{ items: Values[] }>(
    `/consignments/${id}/compliance-cases`,
    org,
  );
  return (
    <Section name="Compliance review cases">
      {resource.data?.items.map((c) => (
        <details key={String(c.id)}>
          <summary className="cursor-pointer text-sm font-medium">
            {String(c.case_type)} / {String(c.status)}
          </summary>
          <Facts
            values={{
              evaluation: c.origin_evaluation_id,
              requirement: c.requirement_id,
            }}
          />
          {canRespond && (
            <ActionForm
              name="Record case response"
              key={String(c.id) + String(c.etag)}
              path={`/compliance-cases/${c.id}/actions`}
              initial={{
                evaluation_id: c.origin_evaluation_id,
                requirement_id: c.requirement_id,
                action: "ADD_COMMENT",
              }}
              etag={String(c.etag)}
              specs={[
                {
                  path: "action",
                  label: "Action",
                  kind: "select",
                  options: [
                    "ADD_COMMENT",
                    "FIX_SOURCE",
                    "SUPPLY_MISSING_FACT",
                    "REQUEST_RULE_SCOPE_EXTENSION",
                    ...(canResolve && c.case_type === "POLICY_WARNING"
                      ? ["ACKNOWLEDGE_POLICY_WARNING"]
                      : []),
                  ],
                },
                ...(canResolve
                  ? [
                      {
                        path: "followup_evaluation_id",
                        label: "Corrected evaluation",
                        kind: "select" as const,
                        options: {
                          [currentEvaluation.id]: `${currentEvaluation.action} / ${currentEvaluation.decision}`,
                        },
                      },
                    ]
                  : []),
                ...reason,
              ]}
              reload={async () => {
                await resource.reload();
                await reload();
              }}
            />
          )}
        </details>
      ))}
    </Section>
  );
}

function EvaluationHistory({
  id,
  current,
}: {
  id: string;
  current: Evaluation;
}) {
  const { org } = useTradeContext();
  const [cursor, setCursor] = useState("");
  const [selected, setSelected] = useState("");
  const history = useOperationsResource<{
    items: Values[];
    next_cursor: string | null;
  }>(
    `/consignments/${id}/compliance-evaluations${cursor ? `?cursor=${cursor}` : ""}`,
    org,
  );
  const reload = history.reload;
  useEffect(() => {
    void reload();
  }, [current.id, current.job_state, reload]);
  return (
    <details>
      <summary className="cursor-pointer font-semibold">
        Previous evaluations
      </summary>
      <div className="space-y-3 py-3">
        {history.error && <p role="alert">{history.error}</p>}
        <select
          aria-label="Evaluation history"
          className="w-full rounded border p-2"
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="">Select an immutable evaluation</option>
          {history.data?.items.map((row) => (
            <option key={String(row.id)} value={String(row.id)}>
              {String(row.action)} / {String(row.decision ?? row.job_state)} /{" "}
              {String(row.evaluated_at ?? "queued")}
            </option>
          ))}
        </select>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="icon"
            title="Newest evaluation page"
            aria-label="Newest evaluation page"
            disabled={!cursor}
            onClick={() => {
              setCursor("");
              setSelected("");
            }}
          >
            <RefreshCw className="size-4" />
          </Button>
          {history.data?.next_cursor && (
            <Button
              variant="outline"
              onClick={() => {
                setCursor(history.data!.next_cursor!);
                setSelected("");
              }}
            >
              Older evaluations
            </Button>
          )}
        </div>
        {selected && <HistoricalEvaluation id={selected} />}
      </div>
    </details>
  );
}

function HistoricalEvaluation({ id }: { id: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Evaluation>(
    `/compliance-evaluations/${id}`,
    org,
  );
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!resource.data) return <p role="status">Loading evaluation...</p>;
  return (
    <>
      <EvaluationView evaluation={resource.data} reload={resource.reload} />
      <EvidenceView evaluation={resource.data} />
    </>
  );
}

function EvidenceView({
  evaluation,
  compact = false,
}: {
  evaluation: Evaluation;
  compact?: boolean;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Values>(
    `/compliance-evaluations/${evaluation.id}/evidence-manifest`,
    org,
  );
  return (
    <Section
      name={
        compact ? "Compliance evidence chain" : "Immutable evidence manifest"
      }
    >
      <Mode mode={evaluation.execution_mode} />
      <Facts
        values={{
          evaluation_hash: evaluation.evaluation_hash,
          freshness: evaluation.freshness,
        }}
      />
      {resource.data && (
        <>
          {compact && (
            <ComplianceEvidenceGraph
              graph={resource.data.graph as EvidenceGraphData}
            />
          )}
          <div className="space-y-3">
            {(resource.data.sources as Values[]).map((s) => (
              <div key={String(s.id)}>
                <a
                  className="font-medium text-accent underline"
                  href={String(s.official_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {String(s.title)}
                </a>
                <p className="break-all text-xs text-secondary">
                  SHA-256 {String(s.source_sha256)}
                </p>
                <p className="text-sm">{String(s.interpretation_note)}</p>
              </div>
            ))}
          </div>
          {!compact && (
            <Button
              variant="outline"
              onClick={() => {
                const file = new Blob(
                  [JSON.stringify(resource.data, null, 2)],
                  { type: "application/json" },
                );
                const url = URL.createObjectURL(file);
                const link = document.createElement("a");
                link.href = url;
                link.download = `compliance-evidence-${evaluation.execution_mode}-${evaluation.id}.json`;
                link.click();
                URL.revokeObjectURL(url);
              }}
            >
              <FileDown className="size-4" />
              Export evidence manifest
            </Button>
          )}
        </>
      )}
      {resource.error && <p role="alert">{resource.error}</p>}
    </Section>
  );
}
function ConstraintView({
  id,
  action,
}: {
  id: string;
  action: DispatchAction;
}) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<Values>(
    `/consignments/${id}/compliance-constraints?action=${action}`,
    org,
  );
  return (
    <Section name="Compliance planning constraints">
      {resource.data && <Facts values={resource.data} />}
      {resource.error && <p role="alert">{resource.error}</p>}
    </Section>
  );
}
