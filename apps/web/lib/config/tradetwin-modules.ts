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
    description: "Manage consignments, routes and shipment events.",
    route: "/dashboard/shipments",
    icon: Boxes,
    relatedIds: ["documents", "compliance", "graph"],
    status: "operational",
    metric: { label: "Active", value: 0 },
    accent: "blue",
  },
  {
    id: "documents",
    title: "Documents",
    shortTitle: "Documents",
    description: "Upload documents and review extracted evidence.",
    route: "/dashboard/documents",
    icon: Files,
    relatedIds: ["shipments", "compliance"],
    status: "operational",
    metric: { label: "Missing", value: 0 },
    accent: "cyan",
  },
  {
    id: "compliance",
    title: "Compliance",
    shortTitle: "Compliance",
    description: "Check shipment requirements and required actions.",
    route: "/dashboard/compliance",
    icon: ShieldCheck,
    relatedIds: ["shipments", "documents", "regulations"],
    status: "operational",
    metric: { label: "Require action", value: 0 },
    accent: "cyan",
  },
  {
    id: "graph",
    title: "Knowledge Graph",
    shortTitle: "Graph",
    description: "Explore shipment, route and evidence connections.",
    route: "/dashboard/graph",
    icon: Network,
    relatedIds: ["shipments", "regulations", "compliance"],
    status: "operational",
    metric: { label: "Relationships", value: 0 },
    accent: "blue",
  },
  {
    id: "risk",
    title: "Risk Intelligence",
    shortTitle: "Risk",
    description: "Review predicted risks and contributing factors.",
    route: "/dashboard/risk",
    icon: TriangleAlert,
    relatedIds: ["compliance", "optimizer", "documents"],
    status: "prototype",
    metric: { label: "High risk", value: 0 },
    accent: "violet",
  },
  {
    id: "optimizer",
    title: "Route Optimizer",
    shortTitle: "Optimizer",
    description: "Compare freight routes, costs and delivery constraints.",
    route: "/dashboard/optimizer",
    icon: Route,
    relatedIds: ["risk", "compliance", "regulations"],
    status: "operational",
    metric: { label: "Alternatives", value: 0 },
    accent: "amber",
  },
  {
    id: "regulations",
    title: "Regulations",
    shortTitle: "Regulations",
    description: "Review rules and affected shipments.",
    route: "/dashboard/regulations",
    icon: Landmark,
    relatedIds: ["compliance", "graph", "optimizer"],
    status: "operational",
    metric: { label: "Recent change", value: 0 },
    accent: "amber",
  },
];

// Keep existing evidence/report URLs available without a duplicate dashboard entry.
export const evidenceWorkspaceModule: TradeTwinModule = {
  id: "evidence",
  title: "Evidence & Reports",
  shortTitle: "Evidence",
  description: "Trace decisions to documents, rules and reviews.",
  route: "/dashboard/evidence",
  icon: FileCheck2,
  relatedIds: ["documents", "compliance", "risk"],
  status: "operational",
  metric: { label: "Pending reviews", value: 0 },
  accent: "violet",
};

export function modulesWithDashboardData(
  summary: DashboardSummaryData,
): TradeTwinModule[] {
  const metrics: Record<
    string,
    { label: string; value: number; isMock: boolean }
  > = {
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
  };

  const unhealthyServices = new Set(
    summary.serviceHealth
      .filter((service) => service.status === "unavailable")
      .map((service) => service.id),
  );

  return tradeTwinModules.map((module) => {
    const requiredServices = moduleServices[module.id] ?? [];
    const isUnavailable = requiredServices.some((service) =>
      unhealthyServices.has(service),
    );

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
};
