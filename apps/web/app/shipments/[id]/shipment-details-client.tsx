"use client";

import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import Link from "next/link";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  buildDemoDocumentPackage,
  complianceFetchBlob,
  complianceFetch,
  type ComplianceAssessment,
  type ConsistencyCheck,
  type ImpactAnalysis,
  type InformationGainQuestion,
  type QuestionAnswerResult,
  type Regulation,
  type RegulationPublishResult,
  type RouteOptimization,
} from "../../../lib/compliance";
import {
  consignmentToClassificationBody,
  getLatestRiskAssessment,
  intelligenceFetch,
  type HSClassificationResponse,
  type RiskAssessment,
} from "../../../lib/intelligence";
import {
  apiFetch,
  displayStatus,
  type Shipment,
  type ShipmentEvent,
  type ShipmentGraph,
} from "../../../lib/shipments";

const eventTypes = [
  "CREATED",
  "LOADED",
  "ARRIVED_AT_TRANSIT_PORT",
  "UNLOADED",
  "TEMPORARY_STORAGE",
  "TRANSSHIPMENT",
  "CONTAINER_OPENED",
  "CONTAINER_RESEALED",
  "ROUTE_CHANGED",
];

export default function ShipmentDetailsClient({ shipmentId }: { shipmentId: string }) {
  const [shipment, setShipment] = useState<Shipment | null>(null);
  const [events, setEvents] = useState<ShipmentEvent[]>([]);
  const [graph, setGraph] = useState<ShipmentGraph>({ nodes: [], edges: [] });
  const [assessments, setAssessments] = useState<ComplianceAssessment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [complianceError, setComplianceError] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [intelligenceError, setIntelligenceError] = useState<string | null>(null);
  const [consistency, setConsistency] = useState<ConsistencyCheck | null>(null);
  const [question, setQuestion] = useState<InformationGainQuestion | null>(null);
  const [hsRecommendations, setHsRecommendations] = useState<
    Record<string, HSClassificationResponse>
  >({});
  const [riskAssessment, setRiskAssessment] = useState<RiskAssessment | null>(null);
  const [routeOptimization, setRouteOptimization] = useState<RouteOptimization | null>(
    null,
  );
  const [impactAnalysis, setImpactAnalysis] = useState<ImpactAnalysis | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [answering, setAnswering] = useState(false);
  const [classifyingConsignmentId, setClassifyingConsignmentId] = useState<string | null>(
    null,
  );
  const [scoringRisk, setScoringRisk] = useState(false);
  const [optimizingRoute, setOptimizingRoute] = useState(false);
  const [publishingRegulation, setPublishingRegulation] = useState(false);
  const [exportingReport, setExportingReport] = useState<"html" | "pdf" | null>(
    null,
  );

  const loadCompliance = useCallback(async () => {
    setComplianceError(null);
    try {
      setAssessments(
        await complianceFetch<ComplianceAssessment[]>(
          `/compliance/assessments/${shipmentId}`,
        ),
      );
    } catch (err) {
      setComplianceError(
        err instanceof Error ? err.message : "Could not load compliance assessments",
      );
    }
  }, [shipmentId]);

  const loadDecisionSupport = useCallback(async () => {
    setDecisionError(null);
    try {
      const [consistencyResult, questionResult] = await Promise.all([
        complianceFetch<ConsistencyCheck>(`/consistency/check/${shipmentId}`, {
          method: "POST",
          body: JSON.stringify({ uploaded_documents: [] }),
        }),
        complianceFetch<InformationGainQuestion[]>(
          `/shipments/${shipmentId}/questions`,
        ),
      ]);
      setConsistency(consistencyResult);
      setQuestion(questionResult[0] ?? null);
    } catch (err) {
      setDecisionError(
        err instanceof Error ? err.message : "Could not load consistency checks",
      );
    }
  }, [shipmentId]);

  const loadIntelligence = useCallback(async () => {
    setIntelligenceError(null);
    try {
      setRiskAssessment(await getLatestRiskAssessment(shipmentId));
    } catch (err) {
      setIntelligenceError(
        err instanceof Error ? err.message : "Could not load intelligence results",
      );
    }
  }, [shipmentId]);

  const loadShipment = useCallback(async () => {
    setError(null);
    try {
      const [shipmentResult, timelineResult, graphResult] = await Promise.all([
        apiFetch<Shipment>(`/shipments/${shipmentId}`),
        apiFetch<{ events: ShipmentEvent[] }>(`/shipments/${shipmentId}/timeline`),
        apiFetch<ShipmentGraph>(`/shipments/${shipmentId}/graph`),
      ]);
      setShipment(shipmentResult);
      setEvents(timelineResult.events);
      setGraph(graphResult);
      await loadCompliance();
      await loadDecisionSupport();
      await loadIntelligence();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load shipment");
    }
  }, [shipmentId, loadCompliance, loadDecisionSupport, loadIntelligence]);

  useEffect(() => {
    void loadShipment();
  }, [loadShipment]);

  async function addEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    setSubmitting(true);
    setError(null);
    const consignmentId = String(formData.get("consignment_id") || "");
    try {
      await apiFetch(`/shipments/${shipmentId}/events`, {
        method: "POST",
        body: JSON.stringify({
          consignment_id: consignmentId === "shipment" ? null : consignmentId,
          event_type: String(formData.get("event_type") || "UNLOADED"),
          location_country: String(formData.get("location_country") || "UAE"),
          occurred_at: new Date().toISOString(),
          metadata: { source: "web-ui" },
        }),
      });
      await loadShipment();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add event");
    } finally {
      setSubmitting(false);
    }
  }

  const flow = useMemo(() => toFlow(graph), [graph]);
  const latestAssessment = assessments[0] ?? null;
  const defaultEventTarget =
    shipment?.consignments.find((consignment) => consignment.destination_country === "UAE")?.id ??
    "shipment";

  async function evaluateCompliance(includeBatteryCertificate: boolean) {
    if (!shipment) {
      return;
    }
    setEvaluating(true);
    setComplianceError(null);
    try {
      const assessment = await complianceFetch<ComplianceAssessment>(
        `/compliance/evaluate/${shipmentId}`,
        {
          method: "POST",
          body: JSON.stringify({
            uploaded_documents: buildDemoDocumentPackage(
              shipment.id,
              includeBatteryCertificate,
            ),
          }),
        },
      );
      setAssessments((current) => [assessment, ...current]);
      await loadDecisionSupport();
    } catch (err) {
      setComplianceError(
        err instanceof Error ? err.message : "Could not evaluate compliance",
      );
    } finally {
      setEvaluating(false);
    }
  }

  async function answerQuestion(answer: string) {
    if (!question || !shipment) {
      return;
    }
    setAnswering(true);
    setDecisionError(null);
    try {
      const result = await complianceFetch<QuestionAnswerResult>(
        `/shipments/${shipmentId}/questions/${question.question_id}/answer`,
        {
          method: "POST",
          body: JSON.stringify({
            answer,
            uploaded_documents: buildDemoDocumentPackage(shipment.id, false),
            metadata: { source: "shipment-details-ui" },
          }),
        },
      );
      setAssessments((current) => [result.assessment, ...current]);
      await loadDecisionSupport();
    } catch (err) {
      setDecisionError(
        err instanceof Error ? err.message : "Could not submit answer",
      );
    } finally {
      setAnswering(false);
    }
  }

  async function classifyConsignment(consignmentId: string) {
    const consignment = shipment?.consignments.find((item) => item.id === consignmentId);
    if (!consignment) {
      return;
    }

    setClassifyingConsignmentId(consignmentId);
    setIntelligenceError(null);
    try {
      const result = await intelligenceFetch<HSClassificationResponse>(
        "/intelligence/hs-classify",
        {
          method: "POST",
          body: JSON.stringify(consignmentToClassificationBody(consignment)),
        },
      );
      setHsRecommendations((current) => ({
        ...current,
        [consignmentId]: result,
      }));
    } catch (err) {
      setIntelligenceError(
        err instanceof Error ? err.message : "Could not classify consignment",
      );
    } finally {
      setClassifyingConsignmentId(null);
    }
  }

  async function scoreRisk() {
    setScoringRisk(true);
    setIntelligenceError(null);
    try {
      setRiskAssessment(
        await intelligenceFetch<RiskAssessment>(
          `/intelligence/risk-score/${shipmentId}`,
          { method: "POST" },
        ),
      );
    } catch (err) {
      setIntelligenceError(
        err instanceof Error ? err.message : "Could not score shipment risk",
      );
    } finally {
      setScoringRisk(false);
    }
  }

  async function optimizeRoute() {
    if (!shipment) {
      return;
    }
    setOptimizingRoute(true);
    setComplianceError(null);
    try {
      setRouteOptimization(
        await complianceFetch<RouteOptimization>(
          `/optimizer/route-options/${shipmentId}`,
          {
            method: "POST",
            body: JSON.stringify({
              uploaded_documents: buildDemoDocumentPackage(shipment.id, false),
            }),
          },
        ),
      );
    } catch (err) {
      setComplianceError(
        err instanceof Error ? err.message : "Could not optimize route",
      );
    } finally {
      setOptimizingRoute(false);
    }
  }

  async function publishDemoRegulationAndAnalyze() {
    if (!shipment) {
      return;
    }
    setPublishingRegulation(true);
    setComplianceError(null);
    try {
      const regulation = await complianceFetch<Regulation>("/regulations", {
        method: "POST",
        body: JSON.stringify({}),
      });
      const published = await complianceFetch<RegulationPublishResult>(
        `/regulations/${regulation.id}/publish-version`,
        { method: "POST" },
      );
      const impact = await complianceFetch<ImpactAnalysis>(
        "/regulations/impact-analysis",
        {
          method: "POST",
          body: JSON.stringify({
            regulation_ids: [published.regulation.id],
            uploaded_documents: buildDemoDocumentPackage(shipment.id, false),
          }),
        },
      );
      setImpactAnalysis(impact);
      await loadCompliance();
    } catch (err) {
      setComplianceError(
        err instanceof Error ? err.message : "Could not analyze regulation impact",
      );
    } finally {
      setPublishingRegulation(false);
    }
  }

  async function exportReport(format: "html" | "pdf") {
    setExportingReport(format);
    setComplianceError(null);
    try {
      const blob = await complianceFetchBlob(
        `/reports/compliance/${shipmentId}?format=${format}`,
        { method: "GET" },
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `tradetwin-${shipmentId}-compliance-report.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setComplianceError(
        err instanceof Error ? err.message : "Could not export report",
      );
    } finally {
      setExportingReport(null);
    }
  }

  if (!shipment) {
    return (
      <main className="min-h-screen bg-[#f6f8fb] px-6 py-6">
        <Link href="/" className="text-sm font-medium text-teal-700">
          Back to shipments
        </Link>
        <p className="mt-6 text-slate-700">{error ?? "Loading shipment..."}</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f6f8fb]">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-6 py-5">
          <Link href="/" className="text-sm font-medium text-teal-700">
            Back to shipments
          </Link>
          <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-slate-500">Shipment Details</p>
              <h1 className="mt-1 text-2xl font-semibold text-slate-950">
                {shipment.shipment_reference}
              </h1>
            </div>
            <span className="rounded bg-amber-100 px-3 py-1.5 text-sm font-medium text-amber-900">
              {displayStatus(shipment.status)}
            </span>
            {latestAssessment ? (
              <span className={statusBadgeClasses(latestAssessment.status)}>
                Compliance {displayStatus(latestAssessment.status)}
              </span>
            ) : null}
            <Link
              href={`/shipments/${shipment.id}/documents`}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Documents
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-6 xl:grid-cols-[1fr_420px]">
        <div className="space-y-6">
          <section className="rounded border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-slate-950">Consignment List</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {shipment.consignments.map((consignment) => (
                <article key={consignment.id} className="rounded border border-slate-200 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-slate-950">
                        {consignment.product_name}
                      </h3>
                      <p className="mt-1 text-sm text-slate-600">
                        {consignment.country_of_origin} to {consignment.destination_country}
                      </p>
                    </div>
                    <span className="rounded bg-emerald-100 px-2.5 py-1 text-sm font-medium text-emerald-900">
                      {displayStatus(consignment.customs_status)}
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-slate-600">
                    {consignment.product_description}
                  </p>
                </article>
              ))}
            </div>
          </section>

          <section className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">
                HS-code Recommendations
              </h2>
              <span className="rounded bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                Human review threshold 72%
              </span>
            </div>
            {intelligenceError ? (
              <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
                {intelligenceError}
              </p>
            ) : null}
            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              {shipment.consignments.map((consignment) => {
                const classification = hsRecommendations[consignment.id];
                return (
                  <article
                    key={consignment.id}
                    className="rounded border border-slate-200 p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h3 className="font-semibold text-slate-950">
                          {consignment.product_name}
                        </h3>
                        <p className="mt-1 text-sm text-slate-600">
                          {consignment.country_of_origin} to{" "}
                          {consignment.destination_country}
                        </p>
                      </div>
                      <button
                        type="button"
                        disabled={classifyingConsignmentId === consignment.id}
                        onClick={() => void classifyConsignment(consignment.id)}
                        className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
                      >
                        {classifyingConsignmentId === consignment.id
                          ? "Classifying..."
                          : "Recommend"}
                      </button>
                    </div>
                    {classification ? (
                      <div className="mt-4 space-y-3">
                        {classification.recommendations.map((recommendation) => (
                          <div
                            key={recommendation.hs_code}
                            className="rounded bg-slate-50 p-3"
                          >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <p className="font-semibold text-slate-950">
                                  {recommendation.hs_code} - {recommendation.title}
                                </p>
                                <p className="mt-1 text-xs text-slate-500">
                                  {recommendation.tariff_notes}
                                </p>
                              </div>
                              <span
                                className={
                                  recommendation.human_review_required
                                    ? "rounded bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900"
                                    : "rounded bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-900"
                                }
                              >
                                {recommendation.human_review_required
                                  ? "Review"
                                  : "Ready"}
                              </span>
                            </div>
                            <ConfidenceMeter value={recommendation.confidence} />
                          </div>
                        ))}
                        <p className="text-xs text-slate-500">
                          Provider: {classification.provider} - {classification.model}
                        </p>
                      </div>
                    ) : (
                      <p className="mt-4 text-sm text-slate-600">
                        No recommendations generated yet.
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          <section className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">Risk Dashboard</h2>
              <button
                type="button"
                disabled={scoringRisk}
                onClick={() => void scoreRisk()}
                className="rounded bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {scoringRisk ? "Scoring..." : "Generate risk score"}
              </button>
            </div>
            <p className="mt-4 rounded bg-amber-50 p-3 text-sm font-medium text-amber-900">
              Prototype prediction based on synthetic or organization-provided data.
            </p>
            {riskAssessment ? (
              <div className="mt-5 space-y-4">
                <div className="grid gap-3 md:grid-cols-4">
                  <RiskMetric
                    label="Inspection"
                    value={`${Math.round(riskAssessment.inspection_probability * 100)}%`}
                  />
                  <RiskMetric
                    label="Rejection"
                    value={`${Math.round(riskAssessment.rejection_probability * 100)}%`}
                  />
                  <RiskMetric
                    label="Delay"
                    value={`${riskAssessment.expected_clearance_delay_hours}h`}
                  />
                  <RiskMetric label="Level" value={riskAssessment.risk_level} />
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  {riskAssessment.risk_factors.map((factor) => (
                    <article key={factor.factor} className="rounded border border-slate-200 p-3">
                      <p className="text-sm font-semibold text-slate-950">{factor.factor}</p>
                      <p className="mt-1 text-xs font-medium text-slate-500">
                        {factor.impact}
                      </p>
                      <p className="mt-2 text-sm text-slate-700">{factor.explanation}</p>
                    </article>
                  ))}
                </div>
                <p className="text-xs text-slate-500">
                  Model: {riskAssessment.model_version} -{" "}
                  {new Date(riskAssessment.created_at).toLocaleString()}
                </p>
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-600">
                No risk assessment generated yet.
              </p>
            )}
          </section>

          <section className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">
                Route Optimization
              </h2>
              <button
                type="button"
                disabled={optimizingRoute}
                onClick={() => void optimizeRoute()}
                className="rounded bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {optimizingRoute ? "Optimizing..." : "Compare routes"}
              </button>
            </div>
            {routeOptimization ? (
              <div className="mt-5 grid gap-3 lg:grid-cols-2">
                {routeOptimization.options.map((option) => (
                  <article
                    key={option.route_id}
                    className={
                      option.is_recommended
                        ? "rounded border border-teal-300 bg-teal-50 p-4"
                        : "rounded border border-slate-200 p-4"
                    }
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h3 className="font-semibold text-slate-950">
                          {option.label}
                        </h3>
                        <p className="mt-1 text-sm text-slate-600">
                          {formatRouteCountries(option.countries)}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {option.is_recommended ? (
                          <span className="rounded bg-teal-700 px-2.5 py-1 text-xs font-medium text-white">
                            Recommended
                          </span>
                        ) : null}
                        <span className={routeLegalBadgeClasses(option.legal_status)}>
                          {displayStatus(option.legal_status)}
                        </span>
                      </div>
                    </div>
                    <p className="mt-3 text-sm text-slate-700">{option.description}</p>
                    <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
                      <RouteFact label="Score" value={String(option.score)} />
                      <RouteFact label="Duty" value={formatMoney(option.estimated_duty)} />
                      <RouteFact
                        label="Risk"
                        value={`${Math.round(option.risk_score * 100)}%`}
                      />
                      <RouteFact label="Delay" value={`${option.estimated_delay_hours}h`} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <span className={statusBadgeClasses(option.compliance_status)}>
                        {displayStatus(option.compliance_status)}
                      </span>
                      {option.fta_eligible ? (
                        <span className="rounded bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-900">
                          FTA eligible
                        </span>
                      ) : null}
                    </div>
                    {option.corrective_actions.length > 0 ? (
                      <ul className="mt-3 space-y-1 text-sm text-slate-700">
                        {option.corrective_actions.slice(0, 3).map((action) => (
                          <li key={action}>{action}</li>
                        ))}
                      </ul>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-600">
                Compare the current India to UAE to Germany route against compliant
                alternate movements.
              </p>
            )}
          </section>

          <section className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">
                Regulatory Change Impact
              </h2>
              <button
                type="button"
                disabled={publishingRegulation}
                onClick={() => void publishDemoRegulationAndAnalyze()}
                className="rounded bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {publishingRegulation ? "Analyzing..." : "Publish UAE rule"}
              </button>
            </div>
            {impactAnalysis ? (
              <div className="mt-5 space-y-3">
                {impactAnalysis.impacted_shipments.length === 0 ? (
                  <p className="text-sm text-slate-600">
                    No active or planned shipments were affected by the selected rule.
                  </p>
                ) : (
                  impactAnalysis.impacted_shipments.map((impact) => (
                    <article
                      key={`${impact.shipment_id}-${impact.triggering_regulation.id}`}
                      className="rounded border border-slate-200 p-4"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h3 className="font-semibold text-slate-950">
                            {impact.shipment_reference}
                          </h3>
                          <p className="mt-1 text-sm text-slate-600">
                            {impact.triggering_regulation.title}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <span className={statusBadgeClasses(impact.previous_status)}>
                            Was {displayStatus(impact.previous_status)}
                          </span>
                          <span className={statusBadgeClasses(impact.new_status)}>
                            Now {displayStatus(impact.new_status)}
                          </span>
                        </div>
                      </div>
                      <p className="mt-3 text-sm text-slate-700">
                        {impact.corrective_action}
                      </p>
                      {impact.route_recommendation ? (
                        <p className="mt-3 rounded bg-teal-50 p-3 text-sm text-teal-900">
                          Alternate route: {impact.route_recommendation.label}
                        </p>
                      ) : null}
                    </article>
                  ))
                )}
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-600">
                Publish the demo UAE lithium transit safety-certificate rule to find
                affected active and planned shipments.
              </p>
            )}
          </section>

          <section className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">Compliance Results</h2>
              {latestAssessment ? (
                <span className={statusBadgeClasses(latestAssessment.status)}>
                  {displayStatus(latestAssessment.status)}
                </span>
              ) : null}
            </div>
            {complianceError ? (
              <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
                {complianceError}
              </p>
            ) : null}
            {!latestAssessment ? (
              <p className="mt-4 text-sm text-slate-600">
                Run a deterministic rules assessment to view consignment outcomes.
              </p>
            ) : (
              <div className="mt-5 space-y-4">
                {latestAssessment.result.consignment_results.map((result) => (
                  <article
                    key={`${result.consignment_id}-${result.jurisdiction}-${result.procedure_type}`}
                    className="rounded border border-slate-200 p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h3 className="font-semibold text-slate-950">
                          {result.product_name}
                        </h3>
                        <p className="mt-1 text-sm text-slate-600">
                          {result.jurisdiction} {displayStatus(result.procedure_type)}
                        </p>
                      </div>
                      <span className={statusBadgeClasses(result.status)}>
                        {displayStatus(result.status)}
                      </span>
                    </div>
                    <div className="mt-4 grid gap-3 lg:grid-cols-2">
                      {result.applicable_rules.map((rule) => (
                        <div key={rule.rule_id} className="rounded border border-slate-200 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <p className="text-sm font-semibold text-slate-950">
                              {rule.title}
                            </p>
                            <span className="text-xs font-medium text-slate-500">
                              v{rule.version}
                            </span>
                          </div>
                          <p className="mt-2 text-xs text-slate-500">{rule.rule_id}</p>
                        </div>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="rounded border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold text-slate-950">
                Consistency Checker
              </h2>
              {consistency ? (
                <span className="text-xs font-medium text-slate-500">
                  Checked {new Date(consistency.checked_at).toLocaleString()}
                </span>
              ) : null}
            </div>
            {decisionError ? (
              <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
                {decisionError}
              </p>
            ) : null}
            {!consistency ? (
              <p className="mt-4 text-sm text-slate-600">Loading consistency checks...</p>
            ) : consistency.conflicts.length === 0 ? (
              <p className="mt-4 text-sm text-slate-600">No consistency conflicts found.</p>
            ) : (
              <div className="mt-5 space-y-3">
                {consistency.conflicts.map((conflict) => (
                  <article
                    key={conflict.conflict_id}
                    className="rounded border border-slate-200 p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h3 className="font-semibold text-slate-950">
                          {conflict.title}
                        </h3>
                        <p className="mt-1 text-sm text-slate-600">
                          {conflict.consignment_name ?? "Shipment level"}
                        </p>
                      </div>
                      <span className={severityBadgeClasses(conflict.severity)}>
                        {displayStatus(conflict.severity)}
                      </span>
                    </div>
                    <p className="mt-3 text-sm text-slate-700">{conflict.details}</p>
                    <div className="mt-3 rounded bg-slate-50 p-3 text-sm text-slate-700">
                      <p className="font-medium text-slate-950">Why this matters</p>
                      <p className="mt-1">{conflict.why_this_matters}</p>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          {latestAssessment ? (
            <section className="grid gap-6 lg:grid-cols-2">
              <div className="rounded border border-slate-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-slate-950">Missing Documents</h2>
                {latestAssessment.result.missing_documents.length > 0 ? (
                  <ul className="mt-4 space-y-2 text-sm text-slate-700">
                    {latestAssessment.result.missing_documents.map((documentType) => (
                      <li key={documentType} className="rounded bg-amber-50 px-3 py-2">
                        {displayStatus(documentType)}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-4 text-sm text-slate-600">No missing documents.</p>
                )}
              </div>
              <div className="rounded border border-slate-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-slate-950">
                  Violations And Corrective Action
                </h2>
                {latestAssessment.result.violations.length > 0 ? (
                  <ul className="mt-4 space-y-2 text-sm text-slate-700">
                    {latestAssessment.result.violations.map((violation) => (
                      <li key={violation} className="rounded bg-red-50 px-3 py-2">
                        {violation}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-4 text-sm text-slate-600">No violations detected.</p>
                )}
                <p className="mt-4 rounded bg-slate-50 p-3 text-sm text-slate-700">
                  {latestAssessment.result.recommended_action}
                </p>
              </div>
            </section>
          ) : null}

          <section className="rounded border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-slate-950">Route Timeline</h2>
            <div className="mt-5 space-y-4">
              {events.map((event) => (
                <article
                  key={event.id}
                  className="grid gap-3 border-l-2 border-teal-600 pl-4 sm:grid-cols-[180px_1fr]"
                >
                  <time className="text-sm text-slate-500">
                    {new Date(event.occurred_at).toLocaleString()}
                  </time>
                  <div>
                    <p className="font-semibold text-slate-950">
                      {displayStatus(event.event_type)}
                    </p>
                    <p className="mt-1 text-sm text-slate-600">{event.location_country}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="rounded border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-slate-950">Shipment Graph</h2>
            <div className="mt-4 h-[520px] rounded border border-slate-200">
              <ReactFlow nodes={flow.nodes} edges={flow.edges} fitView>
                <Background />
                <Controls />
              </ReactFlow>
            </div>
          </section>
        </div>

        <aside className="rounded border border-slate-200 bg-white p-5 xl:sticky xl:top-6 xl:self-start">
          <h2 className="text-lg font-semibold text-slate-950">Add Shipment Event</h2>
          <form onSubmit={addEvent} className="mt-5 space-y-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Event type</span>
              <select
                name="event_type"
                defaultValue="UNLOADED"
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-slate-950 outline-none focus:border-teal-600"
              >
                {eventTypes.map((eventType) => (
                  <option key={eventType} value={eventType}>
                    {displayStatus(eventType)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Target</span>
              <select
                name="consignment_id"
                defaultValue={defaultEventTarget}
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-slate-950 outline-none focus:border-teal-600"
              >
                <option value="shipment">Shipment</option>
                {shipment.consignments.map((consignment) => (
                  <option key={consignment.id} value={consignment.id}>
                    {consignment.product_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Location country</span>
              <input
                name="location_country"
                defaultValue="UAE"
                className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-slate-950 outline-none focus:border-teal-600"
              />
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded bg-teal-700 px-4 py-2.5 font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {submitting ? "Recording..." : "Record event"}
            </button>
          </form>
          {error ? <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}

          <div className="mt-6 border-t border-slate-200 pt-5">
            <h2 className="text-lg font-semibold text-slate-950">Compliance Evaluation</h2>
            <div className="mt-4 space-y-3">
              <button
                type="button"
                disabled={evaluating}
                onClick={() => void evaluateCompliance(false)}
                className="w-full rounded bg-slate-950 px-4 py-2.5 font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {evaluating ? "Evaluating..." : "Evaluate Missing Battery Certificate"}
              </button>
              <button
                type="button"
                disabled={evaluating}
                onClick={() => void evaluateCompliance(true)}
                className="w-full rounded border border-slate-300 px-4 py-2.5 font-semibold text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
              >
                Evaluate Complete Demo Documents
              </button>
            </div>
            {latestAssessment ? (
              <p className="mt-4 text-xs text-slate-500">
                Last assessment: {new Date(latestAssessment.created_at).toLocaleString()}
              </p>
            ) : null}
          </div>

          <div className="mt-6 border-t border-slate-200 pt-5">
            <h2 className="text-lg font-semibold text-slate-950">Report Export</h2>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <button
                type="button"
                disabled={exportingReport !== null}
                onClick={() => void exportReport("html")}
                className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
              >
                {exportingReport === "html" ? "Exporting..." : "HTML"}
              </button>
              <button
                type="button"
                disabled={exportingReport !== null}
                onClick={() => void exportReport("pdf")}
                className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
              >
                {exportingReport === "pdf" ? "Exporting..." : "PDF"}
              </button>
            </div>
          </div>

          <div className="mt-6 border-t border-slate-200 pt-5">
            <h2 className="text-lg font-semibold text-slate-950">
              Recommended Question
            </h2>
            {question ? (
              <div className="mt-4 rounded border border-slate-200 p-3">
                <p className="font-medium text-slate-950">{question.question}</p>
                <div className="mt-3 rounded bg-slate-50 p-3 text-sm text-slate-700">
                  <p className="font-medium text-slate-950">Why this matters</p>
                  <p className="mt-1">{question.why_this_matters}</p>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {question.answer_options.map((option) => (
                    <button
                      key={option}
                      type="button"
                      disabled={answering}
                      onClick={() => void answerQuestion(option)}
                      className="rounded border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
                    >
                      {option}
                    </button>
                  ))}
                </div>
                <p className="mt-3 text-xs text-slate-500">
                  Impact score {question.impact_score}
                </p>
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-600">
                No high-impact questions are pending.
              </p>
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}

function toFlow(graph: ShipmentGraph): { nodes: Node[]; edges: Edge[] } {
  const columns = ["Shipment", "Consignment", "RouteLeg", "ShipmentEvent", "Country"];
  const counters = new Map<string, number>();

  const nodes = graph.nodes.map((node) => {
    const column = Math.max(columns.indexOf(node.type), 0);
    const row = counters.get(node.type) ?? 0;
    counters.set(node.type, row + 1);
    return {
      id: node.id,
      data: { label: node.label },
      position: { x: column * 260, y: row * 110 },
      style: {
        width: 190,
        border: "1px solid #cbd5e1",
        borderRadius: 6,
        color: "#172033",
        background: node.type === "ShipmentEvent" ? "#fff7ed" : "#ffffff",
        fontSize: 12,
      },
    };
  });

  const edges = graph.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label,
    animated: edge.label.includes("AFFECTS"),
    style: { stroke: "#0f766e" },
  }));

  return { nodes, edges };
}

function ConfidenceMeter({ value }: { value: number }) {
  const percent = Math.round(value * 100);
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between text-xs font-medium text-slate-600">
        <span>Confidence</span>
        <span>{percent}%</span>
      </div>
      <div className="mt-1 h-2 rounded bg-slate-200">
        <div
          className="h-2 rounded bg-teal-600"
          style={{ width: `${Math.max(4, Math.min(100, percent))}%` }}
        />
      </div>
    </div>
  );
}

function RiskMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function RouteFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-50 p-2">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function formatRouteCountries(countries: string[]): string {
  return countries.join(" to ");
}

function formatMoney(value: number): string {
  return `$${Math.round(value).toLocaleString()}`;
}

function statusBadgeClasses(status: string): string {
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

function routeLegalBadgeClasses(status: string): string {
  const base = "rounded px-2.5 py-1 text-xs font-medium";
  if (status === "VALID") {
    return `${base} bg-emerald-100 text-emerald-900`;
  }
  return `${base} bg-red-100 text-red-900`;
}

function severityBadgeClasses(severity: string): string {
  const base = "rounded px-3 py-1.5 text-sm font-medium";
  if (severity === "CRITICAL") {
    return `${base} bg-red-100 text-red-900`;
  }
  if (severity === "HIGH") {
    return `${base} bg-amber-100 text-amber-900`;
  }
  if (severity === "MEDIUM") {
    return `${base} bg-sky-100 text-sky-900`;
  }
  return `${base} bg-slate-100 text-slate-700`;
}
