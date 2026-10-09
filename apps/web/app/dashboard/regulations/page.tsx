"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";
import { RegulatorySourcePanel } from "@/components/regulatory-source-panel";

export default function DashboardRegulationsPage() {
  const dashboardModule = tradeTwinModules.find((item) => item.id === "regulations")!;
  return (
    <>
    <RegulatorySourcePanel />
    <ModuleWorkspace
      module={dashboardModule}
      destination={(shipmentId) => `/shipments/${shipmentId}#regulations`}
      actionLabel="Open impact analysis"
    />
    </>
  );
}
