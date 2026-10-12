"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { tradeTwinModules } from "@/lib/config/tradetwin-modules";
import Link from "next/link";
import { FileText } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function DashboardDocumentsPage() {
  const dashboardModule = tradeTwinModules.find(
    (item) => item.id === "documents",
  )!;
  return (
    <>
      <div className="border-b border-line bg-white px-4 py-3">
        <div className="mx-auto max-w-[1320px]">
          <Button asChild variant="outline">
            <Link href="/documents">
              <FileText className="size-4" />
              Trade document desk
            </Link>
          </Button>
        </div>
      </div>
      <ModuleWorkspace
        module={dashboardModule}
        destination={(shipmentId) => `/shipments/${shipmentId}/documents`}
        actionLabel="Open document workspace"
      />
    </>
  );
}
