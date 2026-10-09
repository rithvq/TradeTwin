"use client";

import { useQuery } from "@tanstack/react-query";

import { TradeTwinOrbitalDashboard } from "@/components/dashboard/tradetwin-orbital-dashboard";
import { fetchDashboardSummary } from "@/lib/api/dashboard";
import {
  modulesWithDashboardData,
  tradeTwinModules,
} from "@/lib/config/tradetwin-modules";
import type { DashboardSummaryData } from "@/types/dashboard";

const loadingSummary: DashboardSummaryData = {
  platformStatus: "operational",
  activeShipments: 0,
  highRiskShipments: 0,
  pendingReviews: 0,
  complianceAlerts: 0,
  regulationChanges: 0,
  missingDocuments: 0,
  graphRelationships: 0,
  routeAlternatives: 0,
  serviceHealth: [],
  dataSource: "mock",
  mockFields: [],
  refreshedAt: new Date(0).toISOString(),
};

export default function DashboardPage() {
  const summaryQuery = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: fetchDashboardSummary,
    refetchInterval: 30_000,
  });
  const summary = summaryQuery.data ?? loadingSummary;
  const modules = summaryQuery.data
    ? modulesWithDashboardData(summary)
    : tradeTwinModules;

  return (
    <TradeTwinOrbitalDashboard
      modules={modules}
      summary={summary}
      isLoading={summaryQuery.isLoading}
    />
  );
}
