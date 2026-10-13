"use client";
import { useState } from "react";
import Link from "next/link";
import { Link2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationalMutation } from "@/hooks/use-operations";
import { Section } from "@/components/operations/shared";
import type { ComplianceContext } from "@/lib/guarded-dispatch";

export function EvidenceBindings({
  data,
  reload,
}: {
  data: ComplianceContext;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const mutation = useOperationalMutation(org, reload);
  const [invoice, setInvoice] = useState("");
  const [supporting, setSupporting] = useState<string[]>([]);
  const [observations, setObservations] = useState<string[]>([]);
  const [manual, setManual] = useState<string[]>([]);
  const [transport, setTransport] = useState<string[]>([]);
  const selected = data.documents.filter(
    (d) => d.id === invoice || supporting.includes(d.id),
  );
  function toggle(values: string[], id: string) {
    return values.includes(id)
      ? values.filter((v) => v !== id)
      : [...values, id];
  }
  return (
    <Section name="Exact evidence bindings">
      <Link
        className="text-sm text-accent underline"
        href={`/documents/trades/${data.trade_id}?consignment=${data.consignment_id}`}
      >
        Document review and mapping
      </Link>
      <label className="block text-sm font-medium">
        Complete movement tax invoice
        <select
          className="mt-1 block w-full rounded border p-2"
          value={invoice}
          onChange={(e) => {
            setInvoice(e.target.value);
            setObservations([]);
            setManual([]);
          }}
        >
          <option value="">Select current reviewed invoice</option>
          {data.documents
            .filter((d) => d.document_type === "TAX_INVOICE")
            .map((d) => (
              <option key={d.id} value={d.id}>
                {d.label} /{" "}
                {String(d.reference.document_version_id).slice(0, 8)} /{" "}
                {d.reference.mapping_revision_id
                  ? "mapped"
                  : "mapping required"}
              </option>
            ))}
        </select>
      </label>
      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-semibold">
          Supporting reviewed sources
        </legend>
        {data.documents
          .filter((d) => d.id !== invoice)
          .map((d) => (
            <label key={d.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={supporting.includes(d.id)}
                onChange={() => setSupporting(toggle(supporting, d.id))}
              />
              {d.document_type}: {d.label}
              <span className="text-xs text-secondary">
                v {String(d.reference.document_version_id).slice(0, 8)}
              </span>
            </label>
          ))}
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-semibold">
          Verification observations
        </legend>
        {selected
          .flatMap((d) => d.verification_results)
          .map((r) => (
            <label
              key={r.id}
              className="flex flex-wrap items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                checked={observations.includes(r.id)}
                onChange={() => setObservations(toggle(observations, r.id))}
              />
              {r.check_type} / {r.environment} / {r.method}
              <span className="text-xs text-secondary">
                Fresh until {r.fresh_until}
              </span>
            </label>
          ))}
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-semibold">
          Manual portal observations
        </legend>
        {selected
          .flatMap((d) => d.manual_attestations)
          .map((r) => (
            <label key={r.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={manual.includes(r.id)}
                onChange={() => setManual(toggle(manual, r.id))}
              />
              {r.check_type} / MANUAL_REPORTED / {r.review_outcome}
            </label>
          ))}
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-semibold">
          Assignment-bound transport evidence
        </legend>
        {data.transport_evidence.map((r) => (
          <label key={r.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={transport.includes(r.id)}
              onChange={() => setTransport(toggle(transport, r.id))}
            />
            {r.evidence_type} / {r.review_outcome}
          </label>
        ))}
      </fieldset>
      {mutation.error && (
        <p role="alert" className="text-sm text-red-800">
          {mutation.error.code}: {mutation.error.message}
        </p>
      )}
      <Button
        disabled={
          mutation.pending ||
          !invoice ||
          !data.heads.current_fact_revision_id ||
          !data.heads.current_loading_manifest_revision_id
        }
        onClick={() =>
          void mutation.run(
            `/consignments/${data.consignment_id}/compliance-evidence-binding-revisions`,
            {
              expected_context_version: data.context_version,
              bindings: {
                compliance_fact_revision_id:
                  data.heads.current_fact_revision_id,
                loading_manifest_revision_id:
                  data.heads.current_loading_manifest_revision_id,
                seller_turnover_declaration_id:
                  data.effective_facts.seller_turnover_declaration_id ?? null,
                movement_document: data.documents.find((d) => d.id === invoice)
                  ?.reference,
                supporting_documents: data.documents
                  .filter((d) => supporting.includes(d.id))
                  .map((d) => d.reference),
                verification_result_ids: observations,
                manual_attestation_ids: manual,
                transport_evidence_revision_ids: transport,
              },
            },
            data.etag,
          )
        }
      >
        <Link2 className="size-4" />
        Record binding revision
      </Button>
    </Section>
  );
}
