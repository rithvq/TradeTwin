"use client";
import { useId, useRef, useState } from "react";
import { Upload, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { tradeRequest } from "@/lib/trades";
import { type Attachment, type Consignment } from "@/lib/operations";

export function EvidenceUpload({
  tradeId,
  consignments,
  records,
  reload,
  consignmentOnly = false,
  allowJson = false,
  onUploaded,
  purposeOverride,
}: {
  tradeId: string;
  consignments: Consignment[];
  records: Attachment[];
  reload: () => Promise<void>;
  consignmentOnly?: boolean;
  allowJson?: boolean;
  onUploaded?: (record: Attachment) => Promise<void>;
  purposeOverride?: string;
}) {
  const { org, me } = useTradeContext();
  const formId = useId();
  const [purpose, setPurpose] = useState("OTHER");
  const [consignment, setConsignment] = useState(
    consignmentOnly ? (consignments[0]?.id ?? "") : "",
  );
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const upload = useRef<{
    fingerprint: string;
    record?: Attachment;
    initKey: string;
    completeKey: string;
    stored: boolean;
  } | null>(null);
  const member = me.memberships.find((m) => m.organization_id === org);
  const canUpload = member?.permissions.some(
    (p) =>
      p.permission_code === "attachment.upload" &&
      (!p.trade_id || p.trade_id === tradeId),
  );
  const finance = member?.permissions.some((p) =>
    ["payment.report", "payment.acknowledge"].includes(p.permission_code),
  );
  return (
    <div className="space-y-4">
      <p className="text-sm text-secondary">
        Uploaded evidence: authenticity not assessed.
      </p>
      {canUpload && (
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!file) return;
            setPending(true);
            setError("");
            try {
              const buffer = await file.arrayBuffer();
              const digest = await crypto.subtle.digest("SHA-256", buffer);
              const sha = Array.from(new Uint8Array(digest), (b) =>
                b.toString(16).padStart(2, "0"),
              ).join("");
              const fingerprint = JSON.stringify([
                org,
                tradeId,
                consignment,
                purposeOverride ?? purpose,
                file.name,
                sha,
              ]);
              if (upload.current?.fingerprint !== fingerprint)
                upload.current = {
                  fingerprint,
                  initKey: crypto.randomUUID(),
                  completeKey: crypto.randomUUID(),
                  stored: false,
                };
              const attempt = upload.current;
              let record = attempt.record;
              if (!record) {
                record = await tradeRequest<Attachment>(
                  "/operational-attachments/uploads",
                  org,
                  "POST",
                  {
                    trade_id: tradeId,
                    consignment_id: consignment || null,
                    purpose: purposeOverride ?? purpose,
                    original_name: file.name,
                    content_type: file.type,
                    size_bytes: file.size,
                  },
                  undefined,
                  attempt.initKey,
                );
                attempt.record = record;
              }
              const form = new FormData();
              form.set("file", file);
              if (!attempt.stored) {
                const response = await fetch(record.upload!.url, {
                  method: "PUT",
                  headers: {
                    "X-Organization-Id": org,
                    "Idempotency-Key": record.id,
                  },
                  body: form,
                });
                if (!response.ok) {
                  const problem = await response.json();
                  throw new Error(problem.detail ?? "Encrypted upload failed");
                }
                attempt.stored = true;
              }
              const completed = await tradeRequest<Attachment>(
                `/operational-attachments/${record.id}/completions`,
                org,
                "POST",
                { expected_sha256: sha },
                undefined,
                attempt.completeKey,
              );
              upload.current = null;
              if (onUploaded) await onUploaded(completed);
              await reload();
            } catch (problem) {
              setError(
                problem instanceof Error
                  ? problem.message
                  : "Evidence upload unavailable",
              );
            } finally {
              setPending(false);
            }
          }}
        >
          {!purposeOverride && (
            <div>
              <label
                htmlFor={`${formId}-purpose`}
                className="text-sm font-medium"
              >
                Purpose
              </label>
              <select
                id={`${formId}-purpose`}
                className="mt-1 block w-full rounded border p-2"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
              >
                {[
                  "PICKUP",
                  "INCIDENT",
                  "POD",
                  "RECEIPT",
                  "OTHER",
                  ...(finance ? ["PAYMENT"] : []),
                ].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label
              htmlFor={`${formId}-consignment`}
              className="text-sm font-medium"
            >
              Consignment
            </label>
            <select
              id={`${formId}-consignment`}
              className="mt-1 block w-full rounded border p-2"
              value={consignment}
              onChange={(e) => setConsignment(e.target.value)}
            >
              {!consignmentOnly && <option value="">Trade evidence</option>}
              {consignments.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.reference}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={`${formId}-file`} className="text-sm font-medium">
              Evidence file
            </label>
            <input
              id={`${formId}-file`}
              type="file"
              accept={`application/pdf,image/png,image/jpeg${allowJson ? ",application/json" : ""}`}
              className="mt-1 block w-full text-sm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              required
            />
          </div>
          <div className="self-end">
            <Button disabled={pending || !file}>
              <Upload className="size-4" />
              Upload evidence
            </Button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="text-red-800">
          {error}
        </p>
      )}
      {records.map((r) => (
        <article className="space-y-1 border-b border-line py-3" key={r.id}>
          <strong>{r.original_name}</strong>
          <p className="text-sm">
            {r.purpose} / {r.security_state} / Authenticity not assessed
          </p>
          {r.sha256 && (
            <p className="break-all text-xs text-secondary">
              SHA-256: {r.sha256}
            </p>
          )}
          {r.security_state === "QUARANTINED" && (
            <p className="text-sm text-amber-900">
              Malware scanning is unavailable or inconclusive. Download blocked.
            </p>
          )}
          {r.security_state === "CLEAN" && (
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  const result = await tradeRequest<{ url: string }>(
                    `/operational-attachments/${r.id}/download`,
                    org,
                  );
                  const response = await fetch(result.url, {
                    headers: { "X-Organization-Id": org },
                  });
                  if (!response.ok)
                    throw new Error("Download authorization unavailable");
                  const url = URL.createObjectURL(await response.blob());
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = r.original_name;
                  a.click();
                  URL.revokeObjectURL(url);
                } catch (problem) {
                  setError(
                    problem instanceof Error
                      ? problem.message
                      : "Download failed",
                  );
                }
              }}
            >
              <Download className="size-4" />
              Download
            </Button>
          )}
        </article>
      ))}
    </div>
  );
}
