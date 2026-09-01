"use client";

import Link from "next/link";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  buildDemoDocumentPackage,
  complianceFetch,
  type ComplianceAssessment,
  type UploadedDocumentMetadata,
} from "../../../../lib/compliance";
import {
  documentFetch,
  documentTypeOptions,
  verificationBadgeClasses,
  type EvidenceRecord,
  type TradeDocument,
} from "../../../../lib/documents";
import {
  apiFetch,
  displayStatus,
  type Shipment,
  type ShipmentEvent,
} from "../../../../lib/shipments";

export default function DocumentUploadClient({ shipmentId }: { shipmentId: string }) {
  const [shipment, setShipment] = useState<Shipment | null>(null);
  const [events, setEvents] = useState<ShipmentEvent[]>([]);
  const [documents, setDocuments] = useState<TradeDocument[]>([]);
  const [latestAssessment, setLatestAssessment] = useState<ComplianceAssessment | null>(
    null,
  );
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [extractingDocumentId, setExtractingDocumentId] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);

  const loadEvidence = useCallback(async (assessmentId: string) => {
    const evidenceRecords = await documentFetch<EvidenceRecord[]>(
      `/assessments/${assessmentId}/evidence`,
    );
    setEvidence(evidenceRecords);
  }, []);

  const loadData = useCallback(async () => {
    setError(null);
    try {
      const [shipmentResult, timelineResult, documentResult, assessmentResult] =
        await Promise.all([
          apiFetch<Shipment>(`/shipments/${shipmentId}`),
          apiFetch<{ events: ShipmentEvent[] }>(`/shipments/${shipmentId}/timeline`),
          documentFetch<TradeDocument[]>(`/shipments/${shipmentId}/documents`),
          complianceFetch<ComplianceAssessment[]>(
            `/compliance/assessments/${shipmentId}`,
          ),
        ]);

      setShipment(shipmentResult);
      setEvents(timelineResult.events);
      setDocuments(documentResult);
      const currentAssessment = assessmentResult[0] ?? null;
      setLatestAssessment(currentAssessment);
      if (currentAssessment) {
        await loadEvidence(currentAssessment.id);
      } else {
        setEvidence([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load documents");
    }
  }, [shipmentId, loadEvidence]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const defaultConsignmentId = useMemo(() => {
    const lithium = shipment?.consignments.find((consignment) =>
      consignment.product_name.toLowerCase().includes("lithium"),
    );
    return lithium?.id ?? shipment?.consignments[0]?.id ?? "";
  }, [shipment]);

  const defaultEventId = useMemo(() => {
    const uaeArrival = events.find(
      (event) =>
        event.location_country === "UAE" &&
        event.event_type === "ARRIVED_AT_TRANSIT_PORT",
    );
    return uaeArrival?.id ?? "";
  }, [events]);

  async function uploadDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    setUploading(true);
    setError(null);
    try {
      const uploadedDocument = await documentFetch<TradeDocument>(
        `/shipments/${shipmentId}/documents`,
        {
          method: "POST",
          body: formData,
        },
      );
      setDocuments((current) => [uploadedDocument, ...current]);
      form.reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not upload document");
    } finally {
      setUploading(false);
    }
  }

  async function extractDocument(documentId: string) {
    setExtractingDocumentId(documentId);
    setError(null);
    try {
      const extractedDocument = await documentFetch<TradeDocument>(
        `/documents/${documentId}/extract`,
        { method: "POST" },
      );
      setDocuments((current) =>
        current.map((document) =>
          document.id === documentId ? extractedDocument : document,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not extract document");
    } finally {
      setExtractingDocumentId(null);
    }
  }

  async function reevaluateCompliance() {
    if (!shipment) {
      return;
    }

    setEvaluating(true);
    setError(null);
    try {
      const uploadedDocuments = documents
        .filter((document) => document.verification_status === "EXTRACTED")
        .map(toComplianceDocument);
      const assessment = await complianceFetch<ComplianceAssessment>(
        `/compliance/evaluate/${shipmentId}`,
        {
          method: "POST",
          body: JSON.stringify({
            uploaded_documents: [
              ...buildDemoDocumentPackage(shipment.id, false),
              ...uploadedDocuments,
            ],
          }),
        },
      );
      setLatestAssessment(assessment);
      await loadEvidence(assessment.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reevaluate compliance");
    } finally {
      setEvaluating(false);
    }
  }

  if (!shipment) {
    return (
      <main className="min-h-screen bg-[#f6f8fb] px-6 py-6">
        <Link href="/" className="text-sm font-medium text-teal-700">
          Back to shipments
        </Link>
        <p className="mt-6 text-slate-700">{error ?? "Loading documents..."}</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f6f8fb]">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-6 py-5">
          <div className="flex flex-wrap items-center gap-4">
            <Link
              href={`/shipments/${shipment.id}`}
              className="text-sm font-medium text-teal-700"
            >
              Back to shipment
            </Link>
            <Link href="/" className="text-sm font-medium text-slate-600">
              Shipment list
            </Link>
          </div>
          <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-slate-500">
                Document Intelligence
              </p>
              <h1 className="mt-1 text-2xl font-semibold text-slate-950">
                {shipment.shipment_reference}
              </h1>
            </div>
            {latestAssessment ? (
              <span className={complianceBadgeClasses(latestAssessment.status)}>
                Compliance {displayStatus(latestAssessment.status)}
              </span>
            ) : null}
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-6 xl:grid-cols-[420px_1fr]">
        <aside className="rounded border border-slate-200 bg-white p-5 xl:sticky xl:top-6 xl:self-start">
          <h2 className="text-lg font-semibold text-slate-950">Upload Document</h2>
          <form onSubmit={uploadDocument} className="mt-5 space-y-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Document type</span>
              <select
                name="document_type"
                defaultValue="safety_certificate"
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-slate-950 outline-none focus:border-teal-600"
              >
                {documentTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Consignment</span>
              <select
                name="consignment_id"
                defaultValue={defaultConsignmentId}
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-slate-950 outline-none focus:border-teal-600"
              >
                <option value="">Shipment level</option>
                {shipment.consignments.map((consignment) => (
                  <option key={consignment.id} value={consignment.id}>
                    {consignment.product_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Shipment event</span>
              <select
                name="shipment_event_id"
                defaultValue={defaultEventId}
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-slate-950 outline-none focus:border-teal-600"
              >
                <option value="">Not linked</option>
                {events.map((event) => (
                  <option key={event.id} value={event.id}>
                    {displayStatus(event.event_type)} - {event.location_country}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Jurisdiction</span>
              <input
                name="jurisdiction"
                defaultValue="UAE"
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-slate-950 outline-none focus:border-teal-600"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">File</span>
              <input
                name="file"
                type="file"
                required
                accept="application/pdf,text/plain"
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-950 file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-slate-700 hover:file:bg-slate-200"
              />
            </label>
            <button
              type="submit"
              disabled={uploading}
              className="w-full rounded bg-teal-700 px-4 py-2.5 font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {uploading ? "Uploading..." : "Upload document"}
            </button>
          </form>

          <div className="mt-6 border-t border-slate-200 pt-5">
            <h2 className="text-lg font-semibold text-slate-950">
              Compliance Reevaluation
            </h2>
            <button
              type="button"
              disabled={evaluating}
              onClick={() => void reevaluateCompliance()}
              className="mt-4 w-full rounded bg-slate-950 px-4 py-2.5 font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {evaluating ? "Reevaluating..." : "Reevaluate with evidence"}
            </button>
            {latestAssessment ? (
              <p className="mt-4 text-xs text-slate-500">
                Last assessment: {new Date(latestAssessment.created_at).toLocaleString()}
              </p>
            ) : null}
          </div>

          {error ? (
            <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p>
          ) : null}
        </aside>

        <div className="space-y-6">
          <section className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">
                Uploaded Documents
              </h2>
              <button
                type="button"
                onClick={() => void loadData()}
                className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Refresh
              </button>
            </div>
            <div className="mt-5 space-y-4">
              {documents.length === 0 ? (
                <p className="text-sm text-slate-600">No documents uploaded yet.</p>
              ) : null}
              {documents.map((document) => (
                <article key={document.id} className="rounded border border-slate-200 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-slate-950">{document.filename}</p>
                      <p className="mt-1 text-sm text-slate-600">
                        {displayStatus(document.document_type)} -{" "}
                        {document.jurisdiction ?? "Any jurisdiction"}
                      </p>
                    </div>
                    <span className={verificationBadgeClasses(document.verification_status)}>
                      {displayStatus(document.verification_status)}
                    </span>
                  </div>
                  <div className="mt-4 grid gap-4 lg:grid-cols-[220px_1fr]">
                    <div className="text-sm text-slate-600">
                      <p>Uploaded {new Date(document.uploaded_at).toLocaleString()}</p>
                      <p className="mt-1">
                        {Math.max(1, Math.ceil(document.size_bytes / 1024))} KB
                      </p>
                      <button
                        type="button"
                        disabled={extractingDocumentId === document.id}
                        onClick={() => void extractDocument(document.id)}
                        className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
                      >
                        {extractingDocumentId === document.id
                          ? "Extracting..."
                          : "Extract metadata"}
                      </button>
                    </div>
                    <ExtractedFields document={document} />
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">Evidence Trace</h2>
              {latestAssessment ? (
                <span className={complianceBadgeClasses(latestAssessment.status)}>
                  {displayStatus(latestAssessment.status)}
                </span>
              ) : null}
            </div>
            {evidence.length === 0 ? (
              <p className="mt-4 text-sm text-slate-600">
                Evidence records will appear after a compliance assessment.
              </p>
            ) : (
              <div className="mt-5 space-y-3">
                {evidence.map((record) => (
                  <article key={record.id} className="rounded border border-slate-200 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-slate-950">{record.rule_title}</p>
                        <p className="mt-1 text-sm text-slate-600">
                          {record.jurisdiction} {displayStatus(record.procedure_type)} -
                          v{record.regulation_version}
                        </p>
                      </div>
                      <span className={evidenceBadgeClasses(record.evidence_type)}>
                        {displayStatus(record.evidence_type)}
                      </span>
                    </div>
                    <p className="mt-3 text-sm text-slate-700">{record.explanation}</p>
                    <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
                      <p>Rule: {record.rule_id}</p>
                      <p>Event: {record.shipment_event_id ?? "None"}</p>
                      <p>Document: {record.document?.filename ?? "None"}</p>
                      <p>Source: {record.regulation_source_url}</p>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function ExtractedFields({ document }: { document: TradeDocument }) {
  const entries = Object.entries(document.extracted_fields);

  if (entries.length === 0) {
    return <p className="text-sm text-slate-600">No extracted fields yet.</p>;
  }

  return (
    <dl className="grid gap-2 text-sm sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded bg-slate-50 px-3 py-2">
          <dt className="text-xs font-medium text-slate-500">{displayStatus(key)}</dt>
          <dd className="mt-1 text-slate-800">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function toComplianceDocument(document: TradeDocument): UploadedDocumentMetadata {
  return {
    document_id: document.id,
    document_type: document.document_type,
    filename: document.filename,
    consignment_id: document.consignment_id,
    shipment_event_id: document.shipment_event_id,
    jurisdiction: document.jurisdiction,
    metadata: {
      source: "document-upload-page",
      verification_status: document.verification_status,
      extracted_fields: document.extracted_fields,
      document_number: document.document_number,
      document_date: document.document_date,
    },
  };
}

function complianceBadgeClasses(status: string): string {
  const base = "rounded px-3 py-1.5 text-sm font-medium";
  if (status === "COMPLIANT") {
    return `${base} bg-emerald-100 text-emerald-900`;
  }
  if (status === "CONDITIONALLY_COMPLIANT") {
    return `${base} bg-amber-100 text-amber-900`;
  }
  if (status === "NON_COMPLIANT") {
    return `${base} bg-red-100 text-red-900`;
  }
  return `${base} bg-slate-100 text-slate-700`;
}

function evidenceBadgeClasses(evidenceType: string): string {
  const base = "rounded px-2.5 py-1 text-xs font-medium";
  if (evidenceType === "DOCUMENT_SUPPORTS_RULE") {
    return `${base} bg-emerald-100 text-emerald-900`;
  }
  if (evidenceType === "DOCUMENT_MISSING") {
    return `${base} bg-amber-100 text-amber-900`;
  }
  return `${base} bg-sky-100 text-sky-900`;
}
