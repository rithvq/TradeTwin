"use client";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ClipboardCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDocumentVersion } from "@/hooks/use-document-desk";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import { printable, type Assessment } from "@/lib/document-desk";
import { type Values } from "@/lib/trades";
import { ErrorNotice, Panel, Status } from "./shared";

export function Reconciliation({
  desk,
}: {
  desk: ReturnType<typeof useDocumentVersion>;
}) {
  const { doc, fact, org, version } = desk;
  const [selected, setSelected] = useState("");
  const [related, setRelated] = useState("");
  const [scope, setScope] = useState("");
  const search = useSearchParams();
  const id = selected || search.get("assessment") || doc?.assessments[0]?.id;
  const consignments = useOperationsResource<{
    consignments: { id: string; reference: string }[];
  }>(
    `/trades/${doc?.trade_id ?? "00000000-0000-0000-0000-000000000000"}/operations`,
    org,
  );
  const resource = useOperationsResource<Assessment>(
    `/document-assessment-runs/${id ?? "00000000-0000-0000-0000-000000000000"}`,
    org,
  );
  const register = useOperationsResource<{
    items: { current_version_id: string; label: string }[];
  }>(
    `/trades/${doc?.trade_id ?? "00000000-0000-0000-0000-000000000000"}/documents`,
    org,
  );
  const mutation = useOperationalMutation(org, desk.reload);
  if (!doc || !version) return null;
  return (
    <Panel title="Document reconciliation">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          Comparison scope
          <select
            aria-label="Comparison scope"
            className="mt-1 block rounded border border-line bg-white p-2"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            <option value="">Whole trade</option>
            {consignments.data?.consignments.map((cn) => (
              <option key={cn.id} value={cn.id}>
                {cn.reference}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Related source
          <select
            aria-label="Related comparison document"
            className="mt-1 block rounded border border-line bg-white p-2"
            value={related}
            onChange={(e) => setRelated(e.target.value)}
          >
            <option value="">Accepted trade / operational records</option>
            {register.data?.items
              .filter((d) => d.current_version_id !== version.id)
              .map((d) => (
                <option key={d.current_version_id} value={d.current_version_id}>
                  {d.label}
                </option>
              ))}
          </select>
        </label>
        {fact && doc.allowed_actions.includes("document.check") && (
          <Button
            disabled={mutation.pending}
            onClick={async () => {
              const r = await mutation.run<{ job_id: string }>(
                `/document-versions/${version.id}/assessment-runs`,
                {
                  fact_revision_id: fact.id,
                  mapping_revision_id: doc.current_mapping_revision_id,
                  scope: scope ? "CONSIGNMENT" : "TRADE",
                  consignment_ids: scope ? [scope] : [],
                  related_document_version_ids: related ? [related] : [],
                },
              );
              if (r) desk.watchJob(r.job_id);
            }}
          >
            <ClipboardCheck className="size-4" />
            Run data checks
          </Button>
        )}
        {!!doc.assessments.length && (
          <label className="text-sm">
            Assessment history
            <select
              aria-label="Assessment history"
              className="mt-1 block rounded border border-line bg-white p-2"
              value={id}
              onChange={(e) => setSelected(e.target.value)}
            >
              {doc.assessments.map((a, index) => (
                <option key={a.id} value={a.id}>
                  {index === 0 ? "Latest" : "Previous"} / {a.freshness} /{" "}
                  {a.created_at}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <ErrorNotice
        message={mutation.error?.message ?? (id ? resource.error : "")}
      />
      {resource.data && (
        <>
          <div className="flex flex-wrap gap-2">
            <Status value={resource.data.freshness} />
            <Status value={resource.data.assessment_stage} />
            <Status value={resource.data.consistency} />
            <span className="text-xs text-secondary">
              {resource.data.check_pack_version}
            </span>
          </div>
          <div className="space-y-4">
            {resource.data.findings.map((finding) => (
              <article
                key={finding.id}
                className="space-y-3 border-b border-line pb-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="break-all text-sm">
                    {finding.check_code}
                  </strong>
                  <Status value={finding.outcome} />
                  <Status value={finding.severity} />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Source
                    title="Expected"
                    source={finding.expected_source_json}
                    value={finding.expected_value_json}
                  />
                  <Source
                    title="Document"
                    source={finding.observed_source_json}
                    value={finding.observed_value_json}
                  />
                </div>
                <p className="text-sm">{finding.message}</p>
                {finding.limitations_json.map((text) => (
                  <p key={text} className="text-xs text-secondary">
                    {text}
                  </p>
                ))}
                <div className="flex flex-wrap gap-3 text-xs">
                  <Link
                    className="text-accent underline"
                    href={`/documents/versions/${version.id}/review`}
                  >
                    Review extraction
                  </Link>
                  <Link
                    className="text-accent underline"
                    href={`/trades/${doc.trade_id}`}
                  >
                    Agreement / amendment
                  </Link>
                  <Link
                    className="text-accent underline"
                    href={`/shipments/trades/${doc.trade_id}/operations`}
                  >
                    Assignment / receipt / payment
                  </Link>
                </div>
                {doc.allowed_actions.includes("document.check") && (
                  <FindingAnnotation id={finding.id} org={org} />
                )}
              </article>
            ))}
          </div>
        </>
      )}
      {!id && (
        <p className="text-sm text-secondary">
          No document data assessment recorded.
        </p>
      )}
    </Panel>
  );
}
function Source({
  title,
  source,
  value,
}: {
  title: string;
  source: Values;
  value: unknown;
}) {
  const version = source.document_version_id ?? source.version_id;
  const trade = source.trade_id;
  return (
    <div className="min-w-0 border-l-2 border-line pl-3">
      <p className="text-xs text-secondary">{title}</p>
      <p className="mt-1 break-all text-sm font-medium">{printable(value)}</p>
      <p className="mt-1 break-all text-xs text-secondary">
        {String(source.type)} / {String(source.field ?? "")}
      </p>
      {version ? (
        <Link
          className="text-xs text-accent underline"
          href={`/documents/versions/${String(version)}/review`}
        >
          Open exact source
        </Link>
      ) : trade ? (
        <Link
          className="text-xs text-accent underline"
          href={`/trades/${String(trade)}`}
        >
          Accepted source revision
        </Link>
      ) : null}
    </div>
  );
}
function FindingAnnotation({ id, org }: { id: string; org: string }) {
  const [action, setAction] = useState("ACKNOWLEDGE");
  const [note, setNote] = useState("");
  const mutation = useOperationalMutation(org, async () => {});
  return (
    <details>
      <summary className="cursor-pointer text-xs font-medium">
        Annotate finding
      </summary>
      <form
        className="mt-2 flex flex-wrap gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          await mutation.run(`/document-findings/${id}/annotations`, {
            action,
            note,
          });
        }}
      >
        <select
          aria-label="Finding annotation action"
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="rounded border border-line bg-white p-2 text-xs"
        >
          {[
            "ACKNOWLEDGE",
            "REQUEST_EXTRACTION_CORRECTION",
            "REQUEST_SOURCE_REPLACEMENT",
            "NOTE_COMMERCIAL_VARIANCE",
          ].map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <input
          aria-label="Finding annotation note"
          required
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="min-w-0 flex-1 rounded border border-line p-2 text-xs"
        />
        <Button variant="outline" disabled={mutation.pending} size="sm">
          Record annotation
        </Button>
      </form>
      <ErrorNotice message={mutation.error?.message ?? ""} />
      {mutation.saved && (
        <p role="status" className="mt-2 text-xs">
          Recorded. Finding outcome unchanged.
        </p>
      )}
    </details>
  );
}
