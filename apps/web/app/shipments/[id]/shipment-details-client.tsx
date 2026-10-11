"use client";

import Link from "next/link";
import { FileText } from "lucide-react";
import dynamic from "next/dynamic";
import RadialOrbitalTimeline from "@/components/ui/radial-orbital-timeline";
import { useShipmentDetails } from "@/hooks/use-shipment-details";
import {
  displayStatus,
  shipmentRoute,
  locationLabel,
  type IndianLocation,
} from "@/lib/shipments";
import { statusBadgeClasses } from "@/components/shipments/status";
import { ClassificationPanel } from "@/components/shipments/classification-panel";
import { RiskPanel } from "@/components/shipments/risk-panel";
import { RouteOptionsPanel } from "@/components/shipments/route-options-panel";
import { RegulationImpactPanel } from "@/components/shipments/regulation-impact-panel";
import { ComplianceResultsPanel } from "@/components/shipments/compliance-results-panel";
import { ConsistencyPanel } from "@/components/shipments/consistency-panel";

const eventTypes = [
  "CREATED",
  "LOADED",
  "ARRIVED_AT_HUB",
  "DELIVERED",
  "UNLOADED",
  "TEMPORARY_STORAGE",
  "TRANSSHIPMENT",
  "CONTAINER_OPENED",
  "CONTAINER_RESEALED",
];

const ShipmentGraphPanel = dynamic(
  () =>
    import("../../../components/shipment-graph-panel").then(
      (module) => module.ShipmentGraphPanel,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[640px] items-center justify-center rounded border border-slate-200 text-sm text-slate-500">
        Loading shipment graph...
      </div>
    ),
  },
);

export default function ShipmentDetailsClient({
  shipmentId,
}: {
  shipmentId: string;
}) {
  const details = useShipmentDetails(shipmentId);
  const {
    shipment,
    events,
    graph,
    error,
    submitting,
    evaluating,
    answering,
    exportingReport,
    orbitalEvents,
    latestAssessment,
    question,
    defaultEventTarget,
    addEvent,
    evaluateCompliance,
    answerQuestion,
    exportReport,
  } = details;

  if (!shipment) {
    return (
      <main className="tt-page px-6 py-8">
        <Link href="/" className="text-sm font-medium text-teal-700">
          Back to shipments
        </Link>
        <p className="mt-6 text-slate-700">{error ?? "Loading shipment..."}</p>
      </main>
    );
  }

  return (
    <main className="tt-page">
      <header className="tt-context-header">
        <div className="mx-auto max-w-[1500px] px-4 py-6 sm:px-6">
          <Link href="/" className="text-sm font-medium text-teal-700">
            Back to shipments
          </Link>
          <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="tt-kicker">Shipment digital twin</p>
              <h1 className="mt-2 text-2xl font-semibold text-slate-950">
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
              className="flex items-center gap-2 rounded border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <FileText className="size-4" aria-hidden="true" />
              Documents
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1500px] gap-6 px-4 py-6 sm:px-6 xl:grid-cols-[1fr_420px]">
        <div className="space-y-6">
          <section className="rounded border border-slate-200 bg-white p-5">
            <h2 className="text-lg font-semibold text-slate-950">
              Consignment List
            </h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {shipment.consignments.map((consignment) => (
                <article
                  key={consignment.id}
                  className="rounded border border-slate-200 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-slate-950">
                        {consignment.product_name}
                      </h3>
                      <p className="mt-1 text-sm text-slate-600">
                        {consignment.domestic
                          ? locationLabel(consignment.domestic.destination)
                          : `${consignment.country_of_origin} to ${consignment.destination_country}`}
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

          <ClassificationPanel
            shipment={shipment}
            hsRecommendations={details.hsRecommendations}
            intelligenceError={details.intelligenceError}
            classifyingConsignmentId={details.classifyingConsignmentId}
            classifyConsignment={details.classifyConsignment}
          />

          <RiskPanel
            shipment={shipment}
            riskAssessment={details.riskAssessment}
            scoringRisk={details.scoringRisk}
            scoreRisk={details.scoreRisk}
          />

          <RouteOptionsPanel
            shipment={shipment}
            routeOptimization={details.routeOptimization}
            optimizingRoute={details.optimizingRoute}
            optimizeRoute={details.optimizeRoute}
          />

          <RegulationImpactPanel
            shipment={shipment}
            regulationRules={details.regulationRules}
            impactAnalysis={details.impactAnalysis}
            publishingRegulation={details.publishingRegulation}
            publishDemoRegulationAndAnalyze={
              details.publishDemoRegulationAndAnalyze
            }
          />

          <ComplianceResultsPanel
            latestAssessment={details.latestAssessment}
            complianceError={details.complianceError}
          />

          <ConsistencyPanel
            consistency={details.consistency}
            decisionError={details.decisionError}
          />

          {latestAssessment ? (
            <section className="grid gap-6 lg:grid-cols-2">
              <div
                id="missing-documents"
                className="scroll-mt-24 rounded border border-slate-200 bg-white p-5"
              >
                <h2 className="text-lg font-semibold text-slate-950">
                  Missing Documents
                </h2>
                {latestAssessment.result.missing_documents.length > 0 ? (
                  <ul className="mt-4 space-y-2 text-sm text-slate-700">
                    {latestAssessment.result.missing_documents.map(
                      (documentType) => (
                        <li
                          key={documentType}
                          className="rounded bg-amber-50 px-3 py-2"
                        >
                          {displayStatus(documentType)}
                        </li>
                      ),
                    )}
                  </ul>
                ) : (
                  <p className="mt-4 text-sm text-slate-600">
                    No missing documents.
                  </p>
                )}
              </div>
              <div
                id="violations"
                className="scroll-mt-24 rounded border border-slate-200 bg-white p-5"
              >
                <h2 className="text-lg font-semibold text-slate-950">
                  Violations And Corrective Action
                </h2>
                {latestAssessment.result.violations.length > 0 ? (
                  <ul className="mt-4 space-y-2 text-sm text-slate-700">
                    {latestAssessment.result.violations.map((violation) => (
                      <li
                        key={violation}
                        className="rounded bg-red-50 px-3 py-2"
                      >
                        {violation}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-4 text-sm text-slate-600">
                    No violations detected.
                  </p>
                )}
                <p className="mt-4 rounded bg-slate-50 p-3 text-sm text-slate-700">
                  {latestAssessment.result.recommended_action}
                </p>
              </div>
            </section>
          ) : null}

          <section
            id="timeline"
            className="scroll-mt-24 rounded border border-slate-200 bg-white p-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="tt-kicker">Live event sequence</p>
                <h2 className="mt-1 text-lg font-semibold text-slate-950">
                  Route Timeline
                </h2>
              </div>
              <span className="text-xs text-slate-500">
                {events.length} events
              </span>
            </div>
            <div className="mt-5">
              {orbitalEvents.length > 0 ? (
                <>
                  <RadialOrbitalTimeline
                    timelineData={orbitalEvents}
                    centerLabel={shipment.shipment_reference}
                    centerDetail={shipmentRoute(shipment)}
                  />
                  <ol className="mt-4 grid gap-x-6 gap-y-3 md:grid-cols-2">
                    {events.map((shipmentEvent) => (
                      <li
                        key={shipmentEvent.id}
                        className="grid grid-cols-[6px_minmax(0,1fr)] gap-3"
                      >
                        <span className="mt-1 block min-h-12 rounded-full bg-teal-400/60" />
                        <div className="pb-2">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-sm font-semibold text-slate-950">
                              {displayStatus(shipmentEvent.event_type)}
                            </p>
                            <time className="text-xs text-slate-500">
                              {new Date(
                                shipmentEvent.occurred_at,
                              ).toLocaleString()}
                            </time>
                          </div>
                          <p className="mt-1 text-sm text-slate-600">
                            {shipmentEvent.metadata.location
                              ? locationLabel(
                                  shipmentEvent.metadata
                                    .location as IndianLocation,
                                )
                              : shipmentEvent.location_country}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </>
              ) : (
                <p className="text-sm text-slate-600">
                  No shipment events recorded.
                </p>
              )}
            </div>
          </section>

          <section
            id="graph"
            className="scroll-mt-24 rounded border border-slate-200 bg-white p-5"
          >
            <h2 className="text-lg font-semibold text-slate-950">
              Shipment Graph
            </h2>
            <div className="mt-4">
              <ShipmentGraphPanel graph={graph} />
            </div>
          </section>
        </div>

        <aside className="tt-panel p-5 xl:sticky xl:top-24 xl:self-start">
          <h2 className="text-lg font-semibold text-slate-950">
            Add Shipment Event
          </h2>
          <form
            id="add-event"
            onSubmit={addEvent}
            className="scroll-mt-24 mt-5 space-y-4"
          >
            <label className="block">
              <span className="text-sm font-medium text-slate-700">
                Event type
              </span>
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
              <span className="text-sm font-medium text-slate-700">
                Event location
              </span>
              {shipment.domestic ? (
                <select
                  name="location"
                  className="mt-2 w-full rounded border border-slate-300 px-3 py-2"
                >
                  {[
                    shipment.domestic.origin,
                    ...shipment.route_legs.flatMap((leg) =>
                      leg.domestic ? [leg.domestic.destination] : [],
                    ),
                  ].map((place, index) => (
                    <option key={index} value={JSON.stringify(place)}>
                      {locationLabel(place)}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  name="location_country"
                  defaultValue="India"
                  className="mt-2 w-full rounded border border-slate-300 px-3 py-2"
                />
              )}
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded bg-teal-700 px-4 py-2.5 font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {submitting ? "Recording..." : "Record event"}
            </button>
          </form>
          {error ? (
            <p className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
              {error}
            </p>
          ) : null}

          <div
            id="evaluate"
            className="scroll-mt-24 mt-6 border-t border-slate-200 pt-5"
          >
            <h2 className="text-lg font-semibold text-slate-950">
              Compliance Evaluation
            </h2>
            <div className="mt-4 space-y-3">
              <button
                type="button"
                disabled={evaluating}
                onClick={() => void evaluateCompliance(null)}
                className="w-full rounded bg-teal-700 px-4 py-2.5 font-semibold text-white disabled:opacity-50"
              >
                {evaluating ? "Evaluating..." : "Evaluate uploaded evidence"}
              </button>
              <button
                type="button"
                disabled={evaluating}
                onClick={() => void evaluateCompliance(false)}
                className="w-full rounded bg-slate-950 px-4 py-2.5 font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {evaluating
                  ? "Evaluating..."
                  : shipment.domestic
                    ? "Demo: Missing E-way Bill"
                    : "Demo: Missing Battery Certificate"}
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
                Last assessment:{" "}
                {new Date(latestAssessment.created_at).toLocaleString()}
              </p>
            ) : null}
          </div>

          <div
            id="reports"
            className="scroll-mt-24 mt-6 border-t border-slate-200 pt-5"
          >
            <h2 className="text-lg font-semibold text-slate-950">
              Report Export
            </h2>
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
                <p className="font-medium text-slate-950">
                  {question.question}
                </p>
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
