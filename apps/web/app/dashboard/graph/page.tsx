"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";

export default function DashboardGraphPage() {
  const dashboardModule = tradeTwinModules.find((item) => item.id === "graph")!;
  return (
    <ModuleWorkspace
      module={dashboardModule}
      destination={(shipmentId) => `/shipments/${shipmentId}#graph`}
      actionLabel="Open shipment graph"
    />
  );
}
