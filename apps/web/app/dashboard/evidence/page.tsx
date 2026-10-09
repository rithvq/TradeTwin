"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";

export default function DashboardEvidencePage() {
  const dashboardModule = tradeTwinModules.find((item) => item.id === "evidence")!;
  return (
    <ModuleWorkspace
      module={dashboardModule}
      destination={(shipmentId) => `/shipments/${shipmentId}/documents#evidence`}
      actionLabel="Open evidence ledger"
    />
  );
}
