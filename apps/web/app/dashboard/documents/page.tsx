"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";

export default function DashboardDocumentsPage() {
  const dashboardModule = tradeTwinModules.find((item) => item.id === "documents")!;
  return (
    <ModuleWorkspace
      module={dashboardModule}
      destination={(shipmentId) => `/shipments/${shipmentId}/documents`}
      actionLabel="Open document workspace"
    />
  );
}
