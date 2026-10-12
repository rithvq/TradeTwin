"use client";
import Link from "next/link";
import { useState } from "react";
import { Download, Play, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDocumentVersion } from "@/hooks/use-document-desk";
import { useOperationalMutation } from "@/hooks/use-operations";
import { tradeRequest } from "@/lib/trades";
import { Dimensions, ErrorNotice, Panel, Status } from "./shared";
import { ReviewDesk } from "./review";
import { Reconciliation } from "./findings";
import { VerificationPanel } from "./verification";
import { DocumentMaintenance } from "./maintenance";

export function DocumentDesk({
  versionId,
  tab,
}: {
  versionId: string;
  tab: string;
}) {
  const desk = useDocumentVersion(versionId);
  const { doc, version, org, job } = desk;
  const mutation = useOperationalMutation(org, desk.reload);
  const [strategy, setStrategy] = useState("AUTO");
  const [exportError, setExportError] = useState("");
  if (desk.error) return <ErrorNotice message={desk.error} />;
  if (!doc || !version)
    return <p role="status">Loading document evidence...</p>;
  const current = doc.current_version_id === versionId;
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href={`/documents/trades/${doc.trade_id}`}
            className="text-sm text-accent underline"
          >
            Document register
          </Link>
          <h1 className="mt-2 text-2xl font-semibold">{doc.label}</h1>
          <p className="mt-1 text-sm text-secondary">
            {doc.document_type} / Source v{version.version_number} /{" "}
            {doc.execution_mode}
          </p>
        </div>
        <Button
          variant="outline"
          size="icon"
          title="Refresh document"
          aria-label="Refresh document"
          onClick={() => void desk.reload()}
        >
          <RefreshCw className="size-4" />
        </Button>
      </header>
      {!current && (
        <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Historical source. Current-source review and verification have not
          been carried forward.
        </p>
      )}
      <Dimensions document={doc} />
      <nav
        aria-label="Document workspace"
        className="flex flex-wrap gap-4 border-b border-line py-3"
      >
        {["processing", "review", "findings", "verification", "evidence"].map(
          (name) => (
            <Link
              key={name}
              aria-current={tab === name ? "page" : undefined}
              className={`text-sm ${tab === name ? "font-semibold text-accent" : "text-secondary"}`}
              href={`/documents/versions/${versionId}/${name}`}
            >
              {name.charAt(0).toUpperCase() + name.slice(1)}
            </Link>
          ),
        )}
        <Link
          className="text-sm text-accent"
          href={`/documents/${doc.id}/mapping`}
        >
          Mapping
        </Link>
      </nav>
      <ErrorNotice message={mutation.error?.message ?? exportError} />
      {tab === "processing" && (
        <>
          <Panel title="Processing">
            <div className="flex flex-wrap items-center gap-3">
              <label className="text-sm">
                Extraction strategy
                <select
                  aria-label="Extraction strategy"
                  className="ml-3 rounded border border-line bg-white p-2"
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value)}
                >
                  {[
                    "AUTO",
                    "NATIVE_TEXT",
                    "OCR",
                    "STRUCTURED_JSON",
                    ...(doc.execution_mode === "SIMULATION"
                      ? ["SIMULATION_FIXTURE"]
                      : []),
                  ].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              {doc.allowed_actions.includes("document.process") && (
                <>
                  <Button
                    disabled={mutation.pending}
                    onClick={async () => {
                      const r = await mutation.run<{ job_id: string }>(
                        `/document-versions/${versionId}/processing-jobs`,
                        { stage: "EXTRACT", strategy, reprocess: false },
                      );
                      if (r) desk.watchJob(r.job_id);
                    }}
                  >
                    <Play className="size-4" />
                    Run extraction
                  </Button>
                  <Button
                    variant="outline"
                    disabled={mutation.pending}
                    onClick={async () => {
                      const r = await mutation.run<{ job_id: string }>(
                        `/document-versions/${versionId}/processing-jobs`,
                        { stage: "EXTRACT", strategy, reprocess: true },
                      );
                      if (r) desk.watchJob(r.job_id);
                    }}
                  >
                    <RefreshCw className="size-4" />
                    Reprocess
                  </Button>
                </>
              )}
            </div>
            {job && (
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <Status value={job.status} />
                  <span className="text-sm">{job.stage}</span>
                  {["QUEUED", "RUNNING"].includes(job.status) &&
                    doc.allowed_actions.includes("document.process") && (
                      <Button
                        variant="outline"
                        size="icon"
                        title="Cancel processing"
                        aria-label="Cancel processing"
                        onClick={() =>
                          void mutation.run(
                            `/document-processing-jobs/${job.id}/cancellations`,
                            { reason: "Cancelled by document operator" },
                            job.etag,
                          )
                        }
                      >
                        <X className="size-4" />
                      </Button>
                    )}
                </div>
                {job.last_error_code && (
                  <p className="text-sm text-amber-900">
                    {job.last_error_code}. Manual transcription remains
                    available.
                  </p>
                )}
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr>
                      <th className="p-2">Attempt</th>
                      <th className="p-2">State</th>
                      <th className="p-2">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {job.attempts.map((a) => (
                      <tr key={String(a.id)}>
                        <td className="p-2">{String(a.attempt_number)}</td>
                        <td className="p-2">{String(a.status)}</td>
                        <td className="p-2">
                          {String(a.error_code ?? "None")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Link
              className="text-sm text-accent underline"
              href={`/documents/versions/${versionId}/review`}
            >
              Open review / manual transcription
            </Link>
          </Panel>
          <DocumentMaintenance desk={desk} />
        </>
      )}
      {tab === "review" && <ReviewDesk desk={desk} />}
      {tab === "findings" && <Reconciliation desk={desk} />}
      {tab === "verification" && <VerificationPanel desk={desk} />}
      {tab === "evidence" && (
        <Panel title="Evidence manifest">
          <p className="break-all text-xs text-secondary">
            Source manifest SHA-256: {version.source_manifest_hash}
          </p>
          <p className="text-sm">
            Review, mapping, comparison, and verification histories are retained
            independently.
          </p>
          <Button
            variant="outline"
            onClick={async () => {
              try {
                const data = await tradeRequest(
                  `/document-versions/${versionId}/evidence-manifest`,
                  org,
                );
                const url = URL.createObjectURL(
                  new Blob([JSON.stringify(data, null, 2)], {
                    type: "application/json",
                  }),
                );
                const a = document.createElement("a");
                a.href = url;
                a.download = `tradetwin-evidence-${versionId}.json`;
                a.click();
                URL.revokeObjectURL(url);
              } catch (e) {
                setExportError(
                  e instanceof Error ? e.message : "Evidence unavailable",
                );
              }
            }}
          >
            <Download className="size-4" />
            Export evidence manifest
          </Button>
          <DocumentMaintenance desk={desk} />
        </Panel>
      )}
    </div>
  );
}
