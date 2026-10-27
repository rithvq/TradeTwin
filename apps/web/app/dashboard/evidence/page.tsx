"use client";

import { ModuleWorkspace } from "@/components/dashboard/module-workspace";
import { evidenceWorkspaceModule } from "@/lib/config/tradetwin-modules";
import Link from "next/link";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function DashboardEvidencePage() {
  return (
    <>
      <div className="mb-4">
        <Button variant="outline" asChild>
          <Link href="/dashboard/evidence/demonstration">
            <Play className="size-4" />
            Guided simulation
          </Link>
        </Button>
      </div>
      <ModuleWorkspace
        module={evidenceWorkspaceModule}
        destination={(shipmentId) =>
          `/shipments/${shipmentId}/documents#evidence`
        }
        actionLabel="Open evidence ledger"
      />
    </>
  );
}
