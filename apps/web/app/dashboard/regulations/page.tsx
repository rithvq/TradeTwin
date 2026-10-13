"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";
import { RegulatorySourcePanel } from "@/components/regulatory-source-panel";
import Link from "next/link";
import { BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function DashboardRegulationsPage() {
  const dashboardModule = tradeTwinModules.find(
    (item) => item.id === "regulations",
  )!;
  return (
    <>
      <div className="mb-4">
        <Button variant="outline" asChild>
          <Link href="/dashboard/regulations/rule-registry">
            <BookOpen className="size-4" />
            Dispatch rule registry
          </Link>
        </Button>
      </div>
      <RegulatorySourcePanel />
      <ModuleWorkspace
        module={dashboardModule}
        destination={(shipmentId) => `/shipments/${shipmentId}#regulations`}
        actionLabel="Open impact analysis"
      />
    </>
  );
}
