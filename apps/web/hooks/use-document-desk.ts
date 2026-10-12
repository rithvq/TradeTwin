"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { tradeRequest } from "@/lib/trades";
import {
  type FactRevision,
  type Job,
  type Observation,
  type SourceVersion,
  type ExtractionRun,
} from "@/lib/document-desk";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "./use-operations";

export function useDocumentVersion(versionId: string) {
  const { org } = useTradeContext();
  const selectedFact = useSearchParams().get("fact");
  const resource = useOperationsResource<SourceVersion>(
    `/document-versions/${versionId}`,
    org,
  );
  const doc = resource.data?.document;
  const fact = useOperationsResource<FactRevision>(
    `/document-fact-revisions/${selectedFact ?? resource.data?.selected_fact_revision_id ?? "00000000-0000-0000-0000-000000000000"}`,
    org,
  );
  const [observations, setObservations] = useState<Observation[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [candidate, setCandidate] = useState<ExtractionRun | null>(null);
  const generation = useRef(0);
  const reloadResource = resource.reload,
    reloadFact = fact.reload;
  const invalidate = useCallback(() => {
    generation.current++;
  }, []);
  const loadObservations = useCallback(async () => {
    const current = ++generation.current;
    try {
      const loaded = await tradeRequest<{ items: ExtractionRun[] }>(
        `/document-versions/${versionId}/extraction-runs`,
        org,
      );
      if (current === generation.current) setRuns(loaded.items);
      const latest =
        candidate ??
        loaded.items.find((r) => r.id === fact.data?.extraction_run_id) ??
        loaded.items.at(-1);
      const value = latest
        ? await tradeRequest<{ items: Observation[] }>(
            `/document-extraction-runs/${latest.id}/observations`,
            org,
          )
        : { items: [] };
      if (current === generation.current) setObservations(value.items);
    } catch (problem) {
      if (current === generation.current)
        setError(
          problem instanceof Error ? problem.message : "Extraction unavailable",
        );
    }
  }, [org, versionId, fact.data?.extraction_run_id, candidate]);
  useEffect(() => {
    void loadObservations();
    return invalidate;
  }, [loadObservations, invalidate]);
  useEffect(() => {
    setObservations([]);
    setJob(null);
    setJobId(null);
    setCandidate(null);
  }, [org, versionId]);
  useEffect(() => {
    if (doc?.latest_job_id) setJobId(doc.latest_job_id);
  }, [doc?.latest_job_id, org, versionId]);
  async function reload() {
    await resource.reload();
    await fact.reload();
    await loadObservations();
  }
  useEffect(() => {
    if (!jobId) return;
    let active = true;
    const poll = async () => {
      try {
        const next = await tradeRequest<Job>(
          `/document-processing-jobs/${jobId}`,
          org,
        );
        if (!active) return;
        setJob(next);
        if (
          ["SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"].includes(next.status)
        ) {
          setJobId(null);
          await reloadResource();
          await reloadFact();
          await loadObservations();
        }
      } catch (problem) {
        if (active) {
          setError(
            problem instanceof Error ? problem.message : "Job unavailable",
          );
          setJobId(null);
        }
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [jobId, org, reloadResource, reloadFact, loadObservations]);
  return {
    org,
    doc,
    version: resource.data,
    fact: fact.data,
    observations,
    runs,
    candidate,
    selectExtraction: setCandidate,
    job,
    watchJob: setJobId,
    reload,
    error:
      resource.error ||
      (fact.data && fact.data.document_version_id !== versionId
        ? "Selected snapshot belongs to another document source."
        : "") ||
      error,
  };
}
