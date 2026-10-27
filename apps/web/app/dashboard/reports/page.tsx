"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { evidenceWorkspaceModule } from "@/lib/config/tradetwin-modules";

export default function DashboardReportsPage() {
  const reportModule = {
    ...evidenceWorkspaceModule,
    id: "reports",
    title: "Compliance Reports",
    shortTitle: "Reports",
    description:
      "Generate evidence-grounded HTML or PDF compliance reports for a selected shipment.",
  };
  return (
    <ModuleWorkspace
      module={reportModule}
      destination={(shipmentId) => `/shipments/${shipmentId}#reports`}
      actionLabel="Open report export"
    />
  );
}
