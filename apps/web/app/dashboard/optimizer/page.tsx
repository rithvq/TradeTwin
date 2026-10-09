"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";

export default function DashboardOptimizerPage() {
  const dashboardModule = tradeTwinModules.find((item) => item.id === "optimizer")!;
  return (
    <ModuleWorkspace
      module={dashboardModule}
      destination={(shipmentId) => `/shipments/${shipmentId}/route-memory`}
      actionLabel="Open route memory"
    />
  );
}
