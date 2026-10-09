import { Activity, BellRing, Landmark, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { DashboardSummaryData } from "@/types/dashboard";

export function DashboardSummary({ summary }: { summary: DashboardSummaryData }) {
  const metrics = [
    { label: "Active shipments", value: summary.activeShipments, icon: Activity },
    { label: "Compliance alerts", value: summary.complianceAlerts, icon: BellRing },
    { label: "High-risk consignments", value: summary.highRiskShipments, icon: TriangleAlert },
    { label: "Regulation changes", value: summary.regulationChanges, icon: Landmark },
  ];

  return (
    <section
      aria-label="Operational summary"
      className="border-y border-line bg-surface"
    >
      <div className="mx-auto grid max-w-[1500px] divide-y divide-line px-4 sm:grid-cols-2 sm:divide-x sm:divide-y-0 sm:px-6 xl:grid-cols-[repeat(4,minmax(0,1fr))_auto]">
        {metrics.map((metric) => {
          const Icon = metric.icon;
          return (
            <div key={metric.label} className="flex min-h-20 items-center gap-3 px-3 py-3 sm:px-5">
              <Icon className="size-4 shrink-0 text-ink" aria-hidden="true" />
              <div>
                <p className="text-xs text-muted">{metric.label}</p>
                <p className="mt-1 text-xl font-semibold text-ink">{metric.value}</p>
              </div>
            </div>
          );
        })}
        <div className="flex items-center px-3 py-4 sm:px-5">
          <Badge variant={summary.dataSource === "live" ? "default" : "outline"}>
            {summary.dataSource === "live" ? "Live metrics" : "Live + demo metrics"}
          </Badge>
        </div>
      </div>
    </section>
  );
}
