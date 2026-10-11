"use client";

import {
  CircleCheck,
  Lock,
  MapPin,
  Package,
  RefreshCw,
  Route,
  Unlock,
  Warehouse,
  type LucideIcon,
} from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { TimelineItem } from "@/components/ui/radial-orbital-timeline";
import {
  buildDemoDocumentPackage,
  complianceFetchBlob,
  complianceFetch,
  type ComplianceAssessment,
  type ComplianceRule,
  type ConsistencyCheck,
  type ImpactAnalysis,
  type InformationGainQuestion,
  type QuestionAnswerResult,
  type Regulation,
  type RegulationPublishResult,
  type RouteOptimization,
} from "@/lib/compliance";
import {
  consignmentToClassificationBody,
  getLatestRiskAssessment,
  intelligenceFetch,
  type HSClassificationResponse,
  type RiskAssessment,
} from "@/lib/intelligence";
import {
  apiFetch,
  displayStatus,
  locationLabel,
  type IndianLocation,
  type Shipment,
  type ShipmentEvent,
  type ShipmentGraph,
} from "@/lib/shipments";

const eventIcons: Record<string, LucideIcon> = {
  CREATED: CircleCheck,
  LOADED: Package,
  ARRIVED_AT_TRANSIT_PORT: MapPin,
  UNLOADED: Package,
  TEMPORARY_STORAGE: Warehouse,
  TRANSSHIPMENT: RefreshCw,
  CONTAINER_OPENED: Unlock,
  CONTAINER_RESEALED: Lock,
  ROUTE_CHANGED: Route,
};

export function useShipmentDetails(shipmentId: string) {
  const [shipment, setShipment] = useState<Shipment | null>(null);
  const [events, setEvents] = useState<ShipmentEvent[]>([]);
  const [graph, setGraph] = useState<ShipmentGraph>({ nodes: [], edges: [] });
  const [assessments, setAssessments] = useState<ComplianceAssessment[]>([]);
  const [regulationRules, setRegulationRules] = useState<ComplianceRule[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [complianceError, setComplianceError] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [intelligenceError, setIntelligenceError] = useState<string | null>(
    null,
  );
  const [consistency, setConsistency] = useState<ConsistencyCheck | null>(null);
  const [question, setQuestion] = useState<InformationGainQuestion | null>(
    null,
  );
  const [hsRecommendations, setHsRecommendations] = useState<
    Record<string, HSClassificationResponse>
  >({});
  const [riskAssessment, setRiskAssessment] = useState<RiskAssessment | null>(
    null,
  );
  const [routeOptimization, setRouteOptimization] =
    useState<RouteOptimization | null>(null);
  const [impactAnalysis, setImpactAnalysis] = useState<ImpactAnalysis | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [answering, setAnswering] = useState(false);
  const [classifyingConsignmentId, setClassifyingConsignmentId] = useState<
    string | null
  >(null);
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
      setRegulationRules(
        await complianceFetch<ComplianceRule[]>("/regulations/rules"),
      );
    } catch (err) {
      setComplianceError(
        err instanceof Error
          ? err.message
          : "Could not load compliance assessments",
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
        err instanceof Error
          ? err.message
          : "Could not load consistency checks",
      );
    }
  }, [shipmentId]);

  const loadIntelligence = useCallback(async () => {
    setIntelligenceError(null);
    try {
      setRiskAssessment(await getLatestRiskAssessment(shipmentId));
    } catch (err) {
      setIntelligenceError(
        err instanceof Error
          ? err.message
          : "Could not load intelligence results",
      );
    }
  }, [shipmentId]);

  const loadShipment = useCallback(async () => {
    setError(null);
    try {
      const [shipmentResult, timelineResult, graphResult] = await Promise.all([
        apiFetch<Shipment>(`/shipments/${shipmentId}`),
        apiFetch<{ events: ShipmentEvent[] }>(
          `/shipments/${shipmentId}/timeline`,
        ),
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
          location_country: shipment?.domestic
            ? "India"
            : String(formData.get("location_country") || "India"),
          occurred_at: new Date().toISOString(),
          metadata: {
            source: "web-ui",
            ...(shipment?.domestic
              ? { location: JSON.parse(String(formData.get("location"))) }
              : {}),
          },
        }),
      });
      await loadShipment();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add event");
    } finally {
      setSubmitting(false);
    }
  }

  const orbitalEvents = useMemo<TimelineItem[]>(
    () =>
      events.map((shipmentEvent, index) => {
        const target = shipmentEvent.consignment_id
          ? (shipment?.consignments.find(
              (consignment) => consignment.id === shipmentEvent.consignment_id,
            )?.product_name ?? "Consignment")
          : "Shipment";
        const relatedIds = [
          events[index - 1]?.id,
          events[index + 1]?.id,
        ].filter((id): id is string => Boolean(id));

        return {
          id: shipmentEvent.id,
          title: displayStatus(shipmentEvent.event_type),
          date: new Date(shipmentEvent.occurred_at).toLocaleString(),
          content: `${shipmentEvent.metadata.location ? locationLabel(shipmentEvent.metadata.location as IndianLocation) : shipmentEvent.location_country} | ${target}`,
          category: shipmentEvent.metadata.location
            ? locationLabel(shipmentEvent.metadata.location as IndianLocation)
            : shipmentEvent.location_country,
          icon: eventIcons[shipmentEvent.event_type] ?? CircleCheck,
          relatedIds,
          status: index === events.length - 1 ? "in-progress" : "completed",
          energy: Math.round(
            35 + ((index + 1) / Math.max(events.length, 1)) * 65,
          ),
        };
      }),
    [events, shipment],
  );
  const latestAssessment = assessments[0] ?? null;
  useEffect(() => {
    if (shipment && window.location.hash) {
      document.getElementById(window.location.hash.slice(1))?.scrollIntoView();
    }
  }, [shipment]);
  const defaultEventTarget =
    shipment?.consignments.find(
      (consignment) => consignment.destination_country === "UAE",
    )?.id ?? "shipment";

  async function evaluateCompliance(includeBatteryCertificate: boolean | null) {
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
            uploaded_documents:
              includeBatteryCertificate === null
                ? []
                : buildDemoDocumentPackage(
                    shipment.id,
                    includeBatteryCertificate,
                    !!shipment.domestic,
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
            uploaded_documents: [],
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
    const consignment = shipment?.consignments.find(
      (item) => item.id === consignmentId,
    );
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
              uploaded_documents: [],
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
            uploaded_documents: [],
          }),
        },
      );
      setImpactAnalysis(impact);
      await loadCompliance();
    } catch (err) {
      setComplianceError(
        err instanceof Error
          ? err.message
          : "Could not analyze regulation impact",
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

  return {
    shipment,
    events,
    graph,
    error,
    complianceError,
    decisionError,
    intelligenceError,
    consistency,
    question,
    hsRecommendations,
    riskAssessment,
    routeOptimization,
    impactAnalysis,
    regulationRules,
    submitting,
    evaluating,
    answering,
    classifyingConsignmentId,
    scoringRisk,
    optimizingRoute,
    publishingRegulation,
    exportingReport,
    orbitalEvents,
    latestAssessment,
    defaultEventTarget,
    loadShipment,
    addEvent,
    evaluateCompliance,
    answerQuestion,
    classifyConsignment,
    scoreRisk,
    optimizeRoute,
    publishDemoRegulationAndAnalyze,
    exportReport,
  };
}

export type ShipmentDetailsState = ReturnType<typeof useShipmentDetails>;
