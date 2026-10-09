"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";

export default function DashboardRiskPage() {
  const dashboardModule = tradeTwinModules.find((item) => item.id === "risk")!;
  return (
    <ModuleWorkspace
      module={dashboardModule}
      destination={(shipmentId) => `/shipments/${shipmentId}#risk`}
      actionLabel="Open risk intelligence"
    />
  );
}
