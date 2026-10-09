import {
  Boxes,
  FileCheck2,
  Files,
  Landmark,
  Network,
  Route,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import type { DashboardSummaryData, TradeTwinModule } from "@/types/dashboard";

export const tradeTwinModules: TradeTwinModule[] = [
  {
    id: "shipments",
    title: "Shipment Twin",
    shortTitle: "Shipments",
    description:
      "Create shipments, consignments, route legs, and operational shipment events.",
    route: "/dashboard/shipments",
    icon: Boxes,
    relatedIds: ["documents", "compliance", "graph"],
    status: "operational",
    metric: { label: "Active", value: 0 },
    quickActions: [
      { label: "Create shipment", route: "/dashboard/shipments/new" },
      { label: "View active shipments", route: "/dashboard/shipments?status=active" },
      { label: "Record shipment event", route: "/dashboard/shipments?action=record-event" },
    ],
    accent: "blue",
  },
  {
    id: "documents",
    title: "Documents",
    shortTitle: "Documents",
    description:
      "Upload invoices, packing lists, certificates, licences, and transit declarations.",
    route: "/dashboard/documents",
    icon: Files,
    relatedIds: ["shipments", "compliance", "evidence"],
    status: "operational",
    metric: { label: "Missing", value: 0 },
    quickActions: [
      { label: "Upload document", route: "/dashboard/documents?action=upload" },
      { label: "Review extracted data", route: "/dashboard/documents?view=extracted" },
      { label: "View missing documents", route: "/dashboard/evidence?view=missing" },
    ],
    accent: "cyan",
  },
  {
    id: "compliance",
    title: "Compliance",
    shortTitle: "Compliance",
    description:
      "Run deterministic export, transit, transshipment, and import assessments by consignment.",
    route: "/dashboard/compliance",
    icon: ShieldCheck,
    relatedIds: ["shipments", "documents", "regulations", "evidence"],
    status: "operational",
    metric: { label: "Require action", value: 0 },
    quickActions: [
      { label: "Run assessment", route: "/dashboard/compliance?action=evaluate" },
      { label: "Review violations", route: "/dashboard/compliance?view=violations" },
      { label: "View required actions", route: "/dashboard/compliance?view=actions" },
    ],
    accent: "cyan",
  },
  {
    id: "graph",
    title: "Knowledge Graph",
    shortTitle: "Graph",
    description:
      "Explore relationships across shipments, consignments, locations, routes, rules, and evidence.",
    route: "/dashboard/graph",
    icon: Network,
    relatedIds: ["shipments", "regulations", "compliance"],
    status: "operational",
    metric: { label: "Relationships", value: 0 },
    quickActions: [
      { label: "Open shipment graph", route: "/dashboard/graph?action=open" },
      { label: "Explore relationships", route: "/dashboard/graph?view=relationships" },
      { label: "View event impact", route: "/dashboard/graph?view=events" },
    ],
    accent: "blue",
  },
  {
    id: "risk",
    title: "Risk Intelligence",
    shortTitle: "Risk",
    description:
      "Review prototype inspection, rejection, penalty, and clearance-delay predictions.",
    route: "/dashboard/risk",
    icon: TriangleAlert,
    relatedIds: ["compliance", "optimizer", "evidence"],
    status: "prototype",
    metric: { label: "High risk", value: 0 },
    quickActions: [
      { label: "Calculate risk", route: "/dashboard/risk?action=calculate" },
      { label: "View risk factors", route: "/dashboard/risk?view=factors" },
      { label: "Review model information", route: "/dashboard/risk?view=model" },
    ],
    accent: "violet",
  },
  {
    id: "optimizer",
    title: "Route Optimizer",
    shortTitle: "Optimizer",
    description:
      "Compare routes, transit jurisdictions, tariffs, agreements, delays, and compliance risk.",
    route: "/dashboard/optimizer",
    icon: Route,
    relatedIds: ["risk", "compliance", "regulations"],
    status: "operational",
    metric: { label: "Alternatives", value: 0 },
    quickActions: [
      { label: "Compare routes", route: "/dashboard/optimizer?action=compare" },
      { label: "Optimize shipment", route: "/dashboard/optimizer?action=optimize" },
      { label: "View rejected alternatives", route: "/dashboard/optimizer?view=rejected" },
    ],
    accent: "amber",
  },
  {
    id: "regulations",
    title: "Regulations",
    shortTitle: "Regulations",
    description:
      "Manage versioned domestic rules and identify shipments affected by regulatory changes.",
    route: "/dashboard/regulations",
    icon: Landmark,
    relatedIds: ["compliance", "graph", "optimizer"],
    status: "operational",
    metric: { label: "Recent change", value: 0 },
    quickActions: [
      { label: "Browse regulations", route: "/dashboard/regulations?view=rules" },
      { label: "Publish rule version", route: "/dashboard/regulations?action=publish" },
      { label: "Run impact analysis", route: "/dashboard/regulations?action=impact" },
    ],
    accent: "amber",
  },
  {
    id: "evidence",
    title: "Evidence & Reports",
    shortTitle: "Evidence",
    description:
      "Trace decisions to regulations, documents, shipment events, and human reviews.",
    route: "/dashboard/evidence",
    icon: FileCheck2,
    relatedIds: ["documents", "compliance", "risk"],
    status: "operational",
    metric: { label: "Pending reviews", value: 0 },
    quickActions: [
      { label: "View evidence", route: "/dashboard/evidence?view=ledger" },
      { label: "Review decision trail", route: "/dashboard/evidence?view=decisions" },
      { label: "Generate compliance report", route: "/dashboard/reports" },
    ],
    accent: "violet",
  },
];

export function modulesWithDashboardData(
  summary: DashboardSummaryData,
): TradeTwinModule[] {
  const metrics: Record<string, { label: string; value: number; isMock: boolean }> = {
    shipments: {
      label: "Active",
      value: summary.activeShipments,
      isMock: summary.mockFields.includes("activeShipments"),
    },
    documents: {
      label: "Missing",
      value: summary.missingDocuments,
      isMock: summary.mockFields.includes("missingDocuments"),
    },
    compliance: {
      label: "Require action",
      value: summary.complianceAlerts,
      isMock: summary.mockFields.includes("complianceAlerts"),
    },
    graph: {
      label: "Relationships",
      value: summary.graphRelationships,
      isMock: summary.mockFields.includes("graphRelationships"),
    },
    risk: {
      label: "High risk",
      value: summary.highRiskShipments,
      isMock: summary.mockFields.includes("highRiskShipments"),
    },
    optimizer: {
      label: "Alternatives",
      value: summary.routeAlternatives,
      isMock: summary.mockFields.includes("routeAlternatives"),
    },
    regulations: {
      label: "Recent change",
      value: summary.regulationChanges,
      isMock: summary.mockFields.includes("regulationChanges"),
    },
    evidence: {
      label: "Pending reviews",
      value: summary.pendingReviews,
      isMock: summary.mockFields.includes("pendingReviews"),
    },
  };

  const unhealthyServices = new Set(
    summary.serviceHealth
      .filter((service) => service.status === "unavailable")
      .map((service) => service.id),
  );

  return tradeTwinModules.map((module) => {
    const requiredServices = moduleServices[module.id] ?? [];
    const isUnavailable = requiredServices.some((service) => unhealthyServices.has(service));

    return {
      ...module,
      status:
        module.id === "risk"
          ? "prototype"
          : isUnavailable
            ? "unavailable"
            : module.status,
      metric: metrics[module.id],
    };
  });
}

const moduleServices: Record<string, string[]> = {
  shipments: ["shipment-service"],
  documents: ["document-service"],
  compliance: ["compliance-service"],
  graph: ["shipment-service"],
  risk: ["intelligence-service"],
  optimizer: ["compliance-service"],
  regulations: ["compliance-service"],
  evidence: ["compliance-service", "document-service"],
};
