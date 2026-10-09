import type { ElementType } from "react";

export type TradeTwinModuleStatus =
  | "operational"
  | "attention"
  | "unavailable"
  | "prototype";

export type DashboardDataSource = "live" | "mixed" | "mock";

export interface TradeTwinModuleMetric {
  label: string;
  value: string | number;
  isMock?: boolean;
}

export interface TradeTwinModuleAction {
  label: string;
  route: string;
}

export interface TradeTwinModule {
  id: string;
  title: string;
  shortTitle: string;
  description: string;
  route: string;
  icon: ElementType;
  relatedIds: string[];
  status: TradeTwinModuleStatus;
  metric?: TradeTwinModuleMetric;
  quickActions: TradeTwinModuleAction[];
  accent: "blue" | "cyan" | "amber" | "red" | "violet";
}

export interface ServiceHealth {
  id: string;
  label: string;
  status: "operational" | "unavailable";
}

export interface DashboardSummaryData {
  platformStatus: "operational" | "degraded" | "unavailable";
  activeShipments: number;
  highRiskShipments: number;
  pendingReviews: number;
  complianceAlerts: number;
  regulationChanges: number;
  missingDocuments: number;
  graphRelationships: number;
  routeAlternatives: number;
  serviceHealth: ServiceHealth[];
  dataSource: DashboardDataSource;
  mockFields: string[];
  refreshedAt: string;
}

export interface DashboardApiSummary {
  platform_status?: DashboardSummaryData["platformStatus"];
  active_shipments?: number;
  high_risk_shipments?: number;
  pending_reviews?: number;
  compliance_alerts?: number;
  regulation_changes?: number;
  missing_documents?: number;
  graph_relationships?: number;
  route_alternatives?: number;
}
