"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";
import { RegulatorySourcePanel } from "@/components/regulatory-source-panel";
import Link from "next/link";
import { BookOpen, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function DashboardRegulationsPage() {
  const dashboardModule = tradeTwinModules.find(
    (item) => item.id === "regulations",
  )!;
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2">
        <Button variant="outline" asChild>
          <Link href="/dashboard/regulations/assurance">
            <ShieldCheck className="size-4" />
            Deployment assurance
          </Link>
        </Button>
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
