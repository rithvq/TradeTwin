"use client";
import { useEffect, useRef, useState } from "react";
import { Check, Plus, Save, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useOperationalMutation } from "@/hooks/use-operations";
import { useDocumentVersion } from "@/hooks/use-document-desk";
import { tradeRequest, type Values } from "@/lib/trades";
import {
  flattenDocument,
  printable,
  setDocumentField,
  type Locator,
  type Observation,
} from "@/lib/document-desk";
import { InputLabel } from "./register";
import { SafePreview } from "./preview";
import { ErrorNotice, Status } from "./shared";

type Decision = {
  decision: string;
  reason: string;
  observation: Observation | null;
  provenance: string;
};
const blank: Values = {
  schema_version: "PH3_CANONICAL_V1",
  header: {},
  parties: {},
  lines: [],
  totals: {},
  packing_transport: {},
  eway_bill: {},
  pod: {},
  payment_evidence: {},
};
export function ReviewDesk({
  desk,
}: {
  desk: ReturnType<typeof useDocumentVersion>;
}) {
  const { doc, fact, observations, org, version, reload } = desk;
  const [canonical, setCanonical] = useState<Values>(blank);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [source, setSource] = useState<Locator | null>(null);
  const [manualPath, setManualPath] = useState("header.document_number");
  const [manualValue, setManualValue] = useState("");
  const [manualReason, setManualReason] = useState("");
  const [extraError, setExtraError] = useState("");
  const initializedReview = useRef("");
  const reviewKey = JSON.stringify([
    org,
    version?.id,
    fact?.id,
    desk.candidate?.id,
  ]);
  const [catalog, setCatalog] = useState<
    { path: string; value_type: string }[]
  >([]);
  const mutation = useOperationalMutation(org, reload);
  const flat = flattenDocument(canonical);
  function observed(path: string, values: Values): Observation | null {
    if (!path.startsWith("lines."))
      return observations.find((o) => o.field_path === path) ?? null;
    const rowKeys = [
      ...new Set(observations.filter((o) => o.row_key).map((o) => o.row_key)),
    ];
    const index = (values.lines as Values[]).findIndex(
      (line) => line.document_line_ref === path.split(".")[1],
    );
    return (
      observations.find(
        (o) =>
          o.field_path === `lines.*.${path.split(".")[2]}` &&
          o.row_key === rowKeys[index],
      ) ?? null
    );
  }
  useEffect(() => {
    if (initializedReview.current === reviewKey) {
      // Immutable source refreshes must not discard in-progress human decisions.
      setDecisions((old) =>
        Object.fromEntries(
          Object.entries(old).map(([path, value]) => [
            path,
            {
              ...value,
              observation:
                value.provenance === "HUMAN_TRANSCRIPTION"
                  ? value.observation
                  : (observed(path, canonical) ?? value.observation),
            },
          ]),
        ),
      );
      return;
    }
    initializedReview.current = reviewKey;
    const value =
      desk.candidate?.proposed_document_json ??
      fact?.canonical_document_json ??
      blank;
    setCanonical(value);
    const initial: Record<string, Decision> = {};
    for (const path of Object.keys(flattenDocument(value))) {
      const saved =
        !desk.candidate || desk.candidate.id === fact?.extraction_run_id
          ? fact?.field_decisions.find((d) => d.field_path === path)
          : undefined;
      initial[path] = {
        decision: saved?.decision ?? "",
        reason: saved?.reason ?? "",
        provenance: saved?.provenance ?? "EXTRACTION_REVIEW",
        observation: observed(path, value),
      };
    }
    setDecisions(initial);
    setExtraError("");
  }, [reviewKey, observations]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    void tradeRequest<{ fields: { path: string; value_type: string }[] }>(
      "/document-field-catalog",
      org,
    )
      .then((d) => setCatalog(d.fields))
      .catch(() => setCatalog([]));
  }, [org]);
  if (!doc || !version) return null;
  const current = doc.current_version_id === version.id;
  const editable = current && doc.allowed_actions.includes("document.review");
  function update(path: string, next: Partial<Decision>) {
    setDecisions((old) => ({ ...old, [path]: { ...old[path], ...next } }));
  }
  async function save() {
    if (!doc || !version || !desk.observationsReady) return;
    setExtraError("");
    if (Object.keys(flat).some((path) => !decisions[path]?.decision)) {
      setExtraError("Choose a review decision for every captured value.");
      return;
    }
    const selected = Object.entries(decisions).filter(
      ([path]) =>
        path in flat ||
        ["UNRESOLVED", "NOT_APPLICABLE"].includes(decisions[path].decision),
    );
    const fieldDecisions = selected.map(([path, value]) => ({
      field_path: path,
      document_line_ref: path.startsWith("lines.") ? path.split(".")[1] : null,
      observation_id: value.observation?.id ?? null,
      decision: value.decision,
      effective_value: flat[path] ?? null,
      provenance: value.observation
        ? "EXTRACTION_REVIEW"
        : "HUMAN_TRANSCRIPTION",
      reason: value.reason || null,
      source_locator: value.observation?.source_locator_json ?? null,
    }));
    const alignments = (canonical.lines as Values[])
      .map((line) => {
        const match = observed(
          `lines.${String(line.document_line_ref)}.quantity`,
          canonical,
        );
        return match?.row_key
          ? {
              candidate_row_key: match.row_key,
              document_line_ref: line.document_line_ref,
            }
          : null;
      })
      .filter(Boolean);
    const saved = await mutation.run(
      `/document-versions/${version.id}/fact-revisions`,
      {
        base_fact_revision_id: fact?.id ?? null,
        extraction_run_id:
          desk.candidate?.id ?? fact?.extraction_run_id ?? null,
        canonical_document: canonical,
        field_decisions: fieldDecisions,
        line_alignments: alignments,
      },
      doc.etag,
    );
    if (saved) desk.selectExtraction(null);
  }
  return (
    <div className="space-y-4">
      <p className="border-l-2 border-accent pl-3 text-sm text-secondary">
        Review confirms captured data; it does not establish document
        authenticity.
      </p>
      <ErrorNotice message={extraError || mutation.error?.message || ""} />
      {editable && desk.runs.length > 1 && (
        <InputLabel text="Extraction source for this draft">
          <select
            value={desk.candidate?.id ?? ""}
            onChange={(e) =>
              desk.selectExtraction(
                desk.runs.find((r) => r.id === e.target.value) ?? null,
              )
            }
          >
            <option value="">Keep the saved review source</option>
            {desk.runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.engine_name} / {r.engine_kind} / {r.created_at}
              </option>
            ))}
          </select>
        </InputLabel>
      )}
      {editable && desk.candidate && (
        <div className="space-y-2">
          {(canonical.lines as Values[]).map((line, index) => (
            <InputLabel key={index} text={`Source row ${index + 1} alignment`}>
              <select
                value={String(line.document_line_ref)}
                onChange={(e) => {
                  const previous = String(line.document_line_ref),
                    next = e.target.value;
                  setCanonical({
                    ...canonical,
                    lines: (canonical.lines as Values[]).map((l, i) =>
                      i === index ? { ...l, document_line_ref: next } : l,
                    ),
                  });
                  setDecisions((old) =>
                    Object.fromEntries(
                      Object.entries(old).map(([path, d]) => [
                        path.replace(`lines.${previous}.`, `lines.${next}.`),
                        d,
                      ]),
                    ),
                  );
                }}
              >
                <option value={String(line.document_line_ref)}>
                  New captured line
                </option>
                {((fact?.canonical_document_json.lines as Values[]) ?? []).map(
                  (l) => (
                    <option
                      key={String(l.document_line_ref)}
                      value={String(l.document_line_ref)}
                    >
                      {String(l.description ?? l.document_line_ref)}
                    </option>
                  ),
                )}
              </select>
            </InputLabel>
          ))}
        </div>
      )}
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <SafePreview versionId={version.id} source={source} />
        <section className="min-w-0 space-y-4">
          <header className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Captured values</h2>
            {editable && observations.length > 0 && (
              <Button
                variant="outline"
                onClick={() =>
                  setDecisions((old) =>
                    Object.fromEntries(
                      Object.entries(old).map(([path, value]) => [
                        path,
                        {
                          ...value,
                          decision:
                            !value.decision &&
                            value.observation?.validation_status === "PARSED"
                              ? "CONFIRMED"
                              : value.decision,
                        },
                      ]),
                    ),
                  )
                }
              >
                <Check className="size-4" />
                Confirm proposed values
              </Button>
            )}
          </header>
          <div className="max-h-[65svh] space-y-3 overflow-y-auto pr-1">
            {Object.entries(flat).map(([path, value]) => {
              const decision = decisions[path];
              const obs = decision?.observation;
              return (
                <article
                  key={path}
                  className="space-y-2 border-b border-line pb-4"
                >
                  <button
                    className="break-all text-left text-xs font-semibold text-accent underline"
                    onClick={() => setSource(obs?.source_locator_json ?? null)}
                  >
                    {path}
                  </button>
                  {obs && (
                    <div className="flex flex-wrap gap-x-3 text-xs text-secondary">
                      <span>Source: {printable(obs.raw_text)}</span>
                      <span>{obs.extraction_method}</span>
                      {obs.provider_confidence !== null && (
                        <span>
                          Confidence:{" "}
                          {Math.round(Number(obs.provider_confidence) * 100)}%
                        </span>
                      )}
                    </div>
                  )}
                  <input
                    aria-label={`Value ${path}`}
                    className="block w-full rounded border border-line bg-white p-2 text-sm"
                    value={
                      typeof value === "object"
                        ? JSON.stringify(value)
                        : String(value)
                    }
                    disabled={!editable}
                    onFocus={() => setSource(obs?.source_locator_json ?? null)}
                    onChange={(e) => {
                      const next =
                        typeof value === "number"
                          ? Number(e.target.value)
                          : typeof value === "boolean"
                            ? e.target.value === "true"
                            : e.target.value;
                      setCanonical(setDocumentField(canonical, path, next));
                      update(path, { decision: "CORRECTED" });
                    }}
                  />
                  {obs?.normalisation_warnings_json.map((warning) => (
                    <p className="text-xs text-amber-900" key={warning}>
                      {warning}
                    </p>
                  ))}
                  <div className="grid gap-2 sm:grid-cols-2">
                    <select
                      aria-label={`Decision ${path}`}
                      disabled={!editable}
                      className="rounded border border-line bg-white p-2 text-xs"
                      value={decision?.decision ?? ""}
                      onChange={(e) => {
                        update(path, { decision: e.target.value });
                        if (
                          ["UNRESOLVED", "NOT_APPLICABLE"].includes(
                            e.target.value,
                          )
                        )
                          setCanonical(setDocumentField(canonical, path, null));
                      }}
                    >
                      <option value="">Choose decision</option>
                      {[
                        "CONFIRMED",
                        "CORRECTED",
                        "UNRESOLVED",
                        "NOT_APPLICABLE",
                      ].map((d) => (
                        <option key={d}>{d}</option>
                      ))}
                    </select>
                    <input
                      aria-label={`Reason ${path}`}
                      disabled={!editable}
                      placeholder="Correction / transcription reason"
                      className="rounded border border-line bg-white p-2 text-xs"
                      value={decision?.reason ?? ""}
                      onChange={(e) => update(path, { reason: e.target.value })}
                    />
                  </div>
                  {decision?.provenance === "HUMAN_TRANSCRIPTION" && (
                    <Status value="HUMAN_TRANSCRIPTION" />
                  )}
                </article>
              );
            })}
            {Object.entries(decisions)
              .filter(
                ([path, d]) =>
                  !(path in flat) &&
                  ["UNRESOLVED", "NOT_APPLICABLE"].includes(d.decision),
              )
              .map(([path, d]) => (
                <p key={path} className="text-sm">
                  <strong>{path}</strong>: {d.decision} / {d.reason}
                </p>
              ))}
            {!Object.keys(flat).length && (
              <p className="text-sm text-secondary">
                No captured fields. Manual transcription is available.
              </p>
            )}
          </div>
          {editable && (
            <details className="border-t border-line pt-3">
              <summary className="cursor-pointer text-sm font-semibold">
                Manual transcription
              </summary>
              <div className="mt-3 grid gap-3">
                <InputLabel text="Field path">
                  <select
                    value={manualPath}
                    onChange={(e) => setManualPath(e.target.value)}
                  >
                    {(catalog.length
                      ? catalog
                      : [
                          {
                            path: "header.document_number",
                            value_type: "STRING",
                          },
                          { path: "header.issue_date", value_type: "DATE" },
                        ]
                    )
                      .filter((f) => !f.path.includes("*"))
                      .map((f) => (
                        <option key={f.path} value={f.path}>
                          {f.path}
                        </option>
                      ))}
                  </select>
                </InputLabel>
                <InputLabel text="Source value">
                  <input
                    value={manualValue}
                    onChange={(e) => setManualValue(e.target.value)}
                  />
                </InputLabel>
                <InputLabel text="Transcription reason">
                  <input
                    value={manualReason}
                    onChange={(e) => setManualReason(e.target.value)}
                  />
                </InputLabel>
                <Button
                  variant="outline"
                  disabled={!manualValue || !manualReason}
                  onClick={() => {
                    const type = catalog.find(
                      (f) => f.path === manualPath,
                    )?.value_type;
                    const value =
                      type === "INTEGER"
                        ? Number(manualValue)
                        : type === "BOOLEAN"
                          ? manualValue === "true"
                          : manualValue;
                    setCanonical(
                      setDocumentField(canonical, manualPath, value),
                    );
                    setDecisions((old) => ({
                      ...old,
                      [manualPath]: {
                        decision: "CORRECTED",
                        reason: manualReason,
                        observation: null,
                        provenance: "HUMAN_TRANSCRIPTION",
                      },
                    }));
                    setManualValue("");
                    setManualReason("");
                  }}
                >
                  <Plus className="size-4" />
                  Add transcribed field
                </Button>
                <Button
                  variant="outline"
                  onClick={async () => {
                    try {
                      const issued = await tradeRequest<{ id: string }>(
                        `/document-versions/${version.id}/line-identities`,
                        org,
                        "POST",
                        { reason: "Manual transcription row" },
                      );
                      const id = issued.id;
                      const lines = (canonical.lines as Values[]) ?? [];
                      setCanonical({
                        ...canonical,
                        lines: [
                          ...lines,
                          {
                            document_line_ref: id,
                            description: null,
                            quantity: null,
                            uqc: null,
                          },
                        ],
                      });
                      setCatalog((old) => [
                        ...old,
                        ...old
                          .filter((f) => f.path.startsWith("lines.*."))
                          .map((f) => ({
                            ...f,
                            path: f.path.replace("*", id),
                          })),
                      ]);
                    } catch (error) {
                      setExtraError(
                        error instanceof Error
                          ? error.message
                          : "Line identity unavailable",
                      );
                    }
                  }}
                >
                  <Plus className="size-4" />
                  Add document line
                </Button>
              </div>
            </details>
          )}
          <div className="flex flex-wrap gap-2">
            {editable && (
              <Button
                disabled={mutation.pending || !desk.observationsReady}
                onClick={() => void save()}
              >
                <Save className="size-4" />
                Save review draft
              </Button>
            )}
            {fact &&
              current &&
              doc.allowed_actions.includes("document.review.submit") && (
                <Button
                  variant="outline"
                  disabled={
                    mutation.pending ||
                    doc.latest_draft_fact_revision_id !== fact.id
                  }
                  onClick={() =>
                    void mutation.run(
                      `/document-fact-revisions/${fact.id}/submissions`,
                      { content_hash: fact.content_hash },
                      doc.etag,
                    )
                  }
                >
                  <Send className="size-4" />
                  Submit reviewed snapshot
                </Button>
              )}
          </div>
          {mutation.saved && (
            <p role="status" className="text-sm text-accent">
              {mutation.saved}. Earlier observations remain in history.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
