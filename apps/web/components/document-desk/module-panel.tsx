"use client";
import Link from "next/link";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { type DocumentSummary, label } from "@/lib/document-desk";
import { type Values } from "@/lib/trades";
import { Panel, Status, ErrorNotice } from "./shared";
import { DocumentGraph } from "./graph";

export function DocumentModulePanel({
  tradeId,
  module,
}: {
  tradeId: string;
  module: string;
}) {
  const { me, org } = useTradeContext();
  const member = me.memberships.find((m) => m.organization_id === org);
  const readable = member?.permissions.some(
    (p) =>
      p.permission_code === "document.read" &&
      (!p.trade_id || p.trade_id === tradeId),
  );
  if (!readable) return module === "Regulations" ? <CheckPack /> : null;
  return <DocumentModuleData tradeId={tradeId} module={module} />;
}
function DocumentModuleData({
  tradeId,
  module,
}: {
  tradeId: string;
  module: string;
}) {
  const { org } = useTradeContext();
  const summary = useOperationsResource<DocumentSummary>(
    `/trades/${tradeId}/document-assessment-summary`,
    org,
  );
  if (summary.error) return <ErrorNotice message={summary.error} />;
  const data = summary.data;
  if (!data)
    return (
      <p role="status" className="text-sm text-secondary">
        Loading document evidence...
      </p>
    );
  if (module === "Graph") return <DocumentGraph graph={data.graph} />;
  if (module === "Regulations") return <CheckPack />;
  return (
    <Panel
      title={
        module === "Risk"
          ? "Document review signals"
          : module === "Compliance"
            ? "Document evidence dimensions"
            : module === "Evidence"
              ? "Document provenance ledger"
              : module === "Optimizer"
                ? "Document context"
                : "Document desk"
      }
    >
      <Link
        className="font-medium text-accent underline"
        href={`/documents/trades/${tradeId}`}
      >
        Open document register
      </Link>
      {module === "Compliance" && (
        <>
          <p className="text-sm">
            Document evidence available for Phase 4 evaluation.
          </p>
          <strong className="text-sm">Dispatch readiness: NOT_ASSESSED</strong>
        </>
      )}
      {module === "Risk" && (
        <>
          <p className="text-sm text-secondary">
            Document discrepancies are review signals, not automatic fraud
            conclusions.
          </p>
          {!data.signals.length && (
            <p className="text-sm">
              No accessible document review signals recorded.
            </p>
          )}
          {data.signals.map((signal, index) => (
            <article
              key={`${signal.id}-${index}`}
              className="space-y-2 border-b border-line py-3"
            >
              <div className="flex flex-wrap gap-2">
                <strong className="text-sm">{signal.check_code}</strong>
                <Status value={signal.severity} />
                <Status value={signal.freshness} />
              </div>
              <p className="text-sm">{signal.message}</p>
              <p className="text-xs text-secondary">
                Assessed: {signal.assessed_at}
              </p>
              <Link
                className="text-xs text-accent underline"
                href={`/documents/versions/${String(signal.observed_source_json.document_version_id)}/findings?assessment=${signal.assessment_id}`}
              >
                Source assessment
              </Link>
            </article>
          ))}
        </>
      )}
      {module !== "Risk" && (
        <div className="space-y-3">
          {data.documents.map((doc) => (
            <article
              key={doc.id}
              className="space-y-2 border-b border-line py-3"
            >
              <Link
                className="font-medium text-accent underline"
                href={`/documents/versions/${doc.current_version_id}/${module === "Evidence" ? "evidence" : module === "Compliance" ? "findings" : "review"}`}
              >
                {doc.label}
              </Link>
              <p className="text-xs text-secondary">
                {doc.document_type} / {doc.execution_mode}
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(doc.status_dimensions).map(([key, value]) => (
                  <span key={key} className="text-xs">
                    <span className="mr-1 text-secondary">{label(key)}:</span>
                    <Status value={value} />
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}
function CheckPack() {
  const { org } = useTradeContext();
  const data = useOperationsResource<Values>("/verification-capabilities", org);
  return (
    <Panel title="Document data-check pack">
      <strong className="text-sm">PH3_DOCUMENT_DATA_CHECKS_V1</strong>
      <p className="text-sm text-secondary">
        Data reconciliation only. Mandatory-document applicability and dispatch
        gating belong to Phase 4.
      </p>
      <ErrorNotice message={data.error} />
      {data.data && (
        <>
          <p className="text-xs">
            Supported profiles:{" "}
            {(data.data.supported_profiles as string[]).join(", ")}
          </p>
          {(data.data.checks as Values[]).map((check) => (
            <p
              key={String(check.check_type)}
              className="flex flex-wrap items-center gap-2 text-xs"
            >
              <span>{String(check.check_type)}</span>
              <Status value={String(check.availability)} />
            </p>
          ))}
          {(data.data.trusted_keys as Values[]).map((key) => (
            <p key={String(key.id)} className="break-all text-xs">
              {String(key.issuer)} / {String(key.provider_environment)} /{" "}
              {String(key.key_fingerprint)}
            </p>
          ))}
        </>
      )}
    </Panel>
  );
}
