"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";

export default function DashboardShipmentsPage() {
  const dashboardModule = tradeTwinModules.find((item) => item.id === "shipments")!;
  return (
    <ModuleWorkspace
      module={dashboardModule}
      destination={(shipmentId) => `/shipments/${shipmentId}`}
      actionLabel="Open digital twin"
    />
  );
}
