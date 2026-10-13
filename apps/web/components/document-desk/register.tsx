"use client";
import { useState } from "react";
import Link from "next/link";
import { FilePlus2, RefreshCw, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EvidenceUpload } from "@/components/operations/evidence-upload";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import { type Operations } from "@/lib/operations";
import { documentTypes, label, type DocumentRecord } from "@/lib/document-desk";
import { ErrorNotice, Panel, Status } from "./shared";

type RegisterData = {
  items: DocumentRecord[];
  next_cursor: string | null;
  allowed_actions: string[];
  execution_mode: string;
};
export function DocumentRegister({
  tradeId,
  consignmentId,
}: {
  tradeId: string;
  consignmentId?: string;
}) {
  const { org } = useTradeContext();
  const [type, setType] = useState("");
  const [reviewState, setReviewState] = useState("");
  const [owner, setOwner] = useState("ALL");
  const [showUpload, setShowUpload] = useState(false);
  const [items, setItems] = useState<DocumentRecord[]>([]);
  const resource = useOperationsResource<RegisterData>(
    `/trades/${tradeId}/documents?${new URLSearchParams({ type, status: reviewState })}`,
    org,
  );
  const operations = useOperationsResource<Operations>(
    `/trades/${tradeId}/operations`,
    org,
  );
  const docs = [...(resource.data?.items ?? []), ...items].filter(
    (doc) =>
      (owner !== "OWN" || doc.owner_organization_id === org) &&
      (!consignmentId ||
        doc.linked_subjects.some(
          (s) =>
            s.subject_type === "CONSIGNMENT" && s.subject_id === consignmentId,
        )),
  );
  async function reload() {
    setItems([]);
    await resource.reload();
    await operations.reload();
  }
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Document register</h1>
          <p className="mt-1 text-sm text-secondary">
            {resource.data?.execution_mode} / Dispatch readiness: Not assessed
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="icon"
            title="Refresh documents"
            aria-label="Refresh documents"
            onClick={() => void reload()}
          >
            <RefreshCw className="size-4" />
          </Button>
          {resource.data?.allowed_actions.includes("document.register") && (
            <Button onClick={() => setShowUpload(!showUpload)}>
              <Upload className="size-4" />
              Upload / reuse
            </Button>
          )}
        </div>
      </header>
      <ErrorNotice message={resource.error} />
      <div className="flex flex-wrap gap-3">
        <label className="text-xs text-secondary">
          Document type
          <select
            aria-label="Document type filter"
            className="mt-1 block rounded border border-line p-2 text-sm text-primary"
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setItems([]);
            }}
          >
            <option value="">All types</option>
            {documentTypes.map((t) => (
              <option key={t} value={t}>
                {label(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-secondary">
          State
          <select
            aria-label="Document state filter"
            className="mt-1 block rounded border border-line p-2 text-sm text-primary"
            value={reviewState}
            onChange={(e) => {
              setReviewState(e.target.value);
              setItems([]);
            }}
          >
            <option value="">All states</option>
            {[
              "UNREVIEWED",
              "IN_REVIEW",
              "REVIEWED",
              "REVIEWED_WITH_UNRESOLVED_FIELDS",
              "DISCREPANCIES_FOUND",
              "CURRENT",
              "STALE",
              "SIMULATION",
              "PRODUCTION",
              "ARCHIVED",
            ].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-secondary">
          Owner
          <select
            aria-label="Document owner filter"
            className="mt-1 block rounded border border-line p-2 text-sm text-primary"
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
          >
            <option value="ALL">All accessible</option>
            <option value="OWN">My organisation</option>
          </select>
        </label>
      </div>
      {showUpload && operations.data && (
        <RegistrationForm
          tradeId={tradeId}
          operations={operations.data}
          initialConsignment={consignmentId}
          reload={reload}
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1000px] text-left text-sm">
          <thead>
            <tr>
              {[
                "Document",
                "Number / issuer",
                "Source",
                "File security",
                "Extraction",
                "Human review",
                "Consistency",
                "Signature",
                "Authority",
                "Freshness",
              ].map((name) => (
                <th
                  key={name}
                  className="border-b border-line p-3 text-xs font-semibold"
                >
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => (
              <tr key={doc.id} className="border-b border-line align-top">
                <td className="p-3">
                  <Link
                    className="font-semibold text-accent underline"
                    href={`/documents/versions/${doc.current_version_id}/review`}
                  >
                    {doc.label}
                  </Link>
                  <p className="mt-1 text-xs text-secondary">
                    {label(doc.document_type)}
                  </p>
                </td>
                <td className="max-w-48 break-all p-3 text-xs">
                  {doc.captured_identity?.document_number ??
                    doc.declared_document_number ??
                    "Not captured"}
                  {doc.captured_identity?.issuer_name && (
                    <p className="mt-1">{doc.captured_identity.issuer_name}</p>
                  )}
                  <p className="mt-1 text-secondary">
                    {doc.owner_organization_id === org
                      ? "My organisation"
                      : "Shared trade party"}
                  </p>
                </td>
                <td className="p-3">v{doc.current_version.version_number}</td>
                {[
                  "file_security",
                  "extraction",
                  "human_review",
                  "data_consistency",
                  "signature_integrity",
                  "authority_lookup",
                  "freshness",
                ].map((key) => (
                  <td key={key} className="p-3">
                    <Status value={doc.status_dimensions[key]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!resource.error && !docs.length && (
        <p className="py-8 text-sm text-secondary">
          No accessible documents match this view.
        </p>
      )}
      {resource.data?.next_cursor && (
        <Button
          variant="outline"
          onClick={async () => {
            const { tradeRequest } = await import("@/lib/trades");
            const next = await tradeRequest<RegisterData>(
              `/trades/${tradeId}/documents?cursor=${items.at(-1)?.id ?? resource.data?.next_cursor}`,
              org,
            );
            setItems((old) => [...old, ...next.items]);
          }}
        >
          Load more
        </Button>
      )}
      <Link
        href={`/shipments/trades/${tradeId}/operations`}
        className="text-sm text-accent underline"
      >
        Trade operations
      </Link>
    </div>
  );
}

function RegistrationForm({
  tradeId,
  operations,
  initialConsignment,
  reload,
}: {
  tradeId: string;
  operations: Operations;
  initialConsignment?: string;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const mutation = useOperationalMutation(org, reload);
  const [type, setType] = useState("TAX_INVOICE");
  const [labelValue, setLabel] = useState("");
  const [attachment, setAttachment] = useState("");
  const [consignment, setConsignment] = useState(initialConsignment ?? "");
  const [number, setNumber] = useState("");
  const [date, setDate] = useState("");
  const [visibility, setVisibility] = useState("OWNER_ONLY");
  const [signed, setSigned] = useState("");
  const clean = operations.documents.filter(
    (a) => a.security_state === "CLEAN",
  );
  return (
    <Panel title="Upload or reuse an immutable file">
      <EvidenceUpload
        tradeId={tradeId}
        consignments={operations.consignments}
        records={[]}
        reload={reload}
        allowJson={type === "SIGNED_EINVOICE_JSON"}
        purposeOverride={
          [
            "FREIGHT_QUOTE",
            "TAX_INVOICE",
            "BILL_OF_SUPPLY",
            "PURCHASE_ORDER",
            "SIGNED_EINVOICE_JSON",
            "PAYMENT_EVIDENCE",
            "OTHER",
          ].includes(type)
            ? "DOCUMENT_FINANCIAL"
            : "DOCUMENT_OPERATIONAL"
        }
        onUploaded={async (a) => setAttachment(a.id)}
      />
      <form
        className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
        onSubmit={async (event) => {
          event.preventDefault();
          await mutation.run(`/trades/${tradeId}/documents`, {
            document_type: type,
            label: labelValue,
            trade_id: tradeId,
            primary_attachment_id: attachment,
            initial_consignment_id: consignment || null,
            declared_document_number: number || null,
            declared_issue_date: date || null,
            visibility,
            supporting_assets: signed
              ? [{ attachment_id: signed, role: "SIGNED_PAYLOAD" }]
              : [],
          });
        }}
      >
        <InputLabel text="Document type">
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {documentTypes.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </InputLabel>
        <InputLabel text="Label">
          <input
            value={labelValue}
            onChange={(e) => setLabel(e.target.value)}
            required
            maxLength={150}
          />
        </InputLabel>
        <InputLabel text="Clean source file">
          <select
            value={attachment}
            onChange={(e) => setAttachment(e.target.value)}
            required
          >
            <option value="">Select scanned file</option>
            {clean.map((a) => (
              <option key={a.id} value={a.id}>
                {a.original_name}
              </option>
            ))}
          </select>
        </InputLabel>
        <InputLabel text="Initial consignment">
          <select
            value={consignment}
            onChange={(e) => setConsignment(e.target.value)}
          >
            <option value="">Trade document</option>
            {operations.consignments.map((c) => (
              <option key={c.id} value={c.id}>
                {c.reference}
              </option>
            ))}
          </select>
        </InputLabel>
        <InputLabel text="Declared number">
          <input
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            maxLength={100}
          />
        </InputLabel>
        <InputLabel text="Declared issue date">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </InputLabel>
        <InputLabel text="Visibility">
          <select
            value={visibility}
            onChange={(e) => setVisibility(e.target.value)}
          >
            <option value="OWNER_ONLY">Owner only</option>
            <option value="TRADE_PARTIES">Trade parties</option>
          </select>
        </InputLabel>
        <InputLabel text="Supporting signed payload">
          <select value={signed} onChange={(e) => setSigned(e.target.value)}>
            <option value="">None</option>
            {clean
              .filter(
                (a) =>
                  a.content_type === "application/json" && a.id !== attachment,
              )
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.original_name}
                </option>
              ))}
          </select>
        </InputLabel>
        <div className="self-end">
          <Button disabled={mutation.pending || !attachment}>
            <FilePlus2 className="size-4" />
            Register document
          </Button>
        </div>
      </form>
      <ErrorNotice message={mutation.error?.message ?? ""} />
      {mutation.saved && (
        <p role="status">Document registered. Extraction has not yet run.</p>
      )}
    </Panel>
  );
}
export function InputLabel({
  text,
  children,
}: {
  text: string;
  children: React.ReactNode;
}) {
  return (
    <label className="min-w-0 text-sm font-medium [&_input]:mt-1 [&_input]:block [&_input]:w-full [&_input]:rounded [&_input]:border [&_input]:border-line [&_input]:bg-white [&_input]:p-2 [&_select]:mt-1 [&_select]:block [&_select]:w-full [&_select]:rounded [&_select]:border [&_select]:border-line [&_select]:bg-white [&_select]:p-2">
      {text}
      {children}
    </label>
  );
}
