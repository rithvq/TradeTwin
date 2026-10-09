"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";

export default function DashboardCompliancePage() {
  const dashboardModule = tradeTwinModules.find((item) => item.id === "compliance")!;
  return (
    <ModuleWorkspace
      module={dashboardModule}
      destination={(shipmentId) => `/shipments/${shipmentId}#compliance`}
      actionLabel="Review compliance"
    />
  );
}
