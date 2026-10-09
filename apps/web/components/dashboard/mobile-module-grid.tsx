import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import { StatusBadge } from "@/components/dashboard/orbital-module-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TradeTwinModule } from "@/types/dashboard";

export function MobileModuleGrid({ modules }: { modules: TradeTwinModule[] }) {
  return (
    <section className="md:hidden" aria-labelledby="mobile-modules-title" data-testid="mobile-module-grid">
      <div className="mb-4">
        <p className="tt-kicker">Control modules</p>
        <h2 id="mobile-modules-title" className="mt-1 text-xl font-semibold text-ink">
          All TradeTwin modules
        </h2>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {modules.map((module) => {
          const Icon = module.icon;
          return (
            <Card key={module.id} className="overflow-hidden bg-surface">
              <CardHeader className="gap-3 pb-3">
                <div className="flex items-start justify-between gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded border border-line bg-soft text-ink">
                    <Icon className="size-5" aria-hidden="true" />
                  </span>
                  <StatusBadge status={module.status} />
                </div>
                <CardTitle>{module.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-secondary">{module.description}</p>
                {module.metric ? (
                  <div className="mt-4 flex items-end justify-between border-y border-line py-3">
                    <span className="text-sm text-muted">{module.metric.label}</span>
                    <span className="text-xl font-semibold text-ink">
                      {module.metric.value}
                      {module.metric.isMock ? (
                        <span className="ml-1 text-xs font-medium text-violet-800">demo</span>
                      ) : null}
                    </span>
                  </div>
                ) : null}
                <div className="mt-4 space-y-2">
                  {module.quickActions.map((action) => (
                    <Link
                      key={action.route}
                      href={action.route}
                      className="flex min-h-9 items-center justify-between rounded px-2 text-sm text-secondary hover:bg-soft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      {action.label}
                      <ArrowUpRight className="size-4" aria-hidden="true" />
                    </Link>
                  ))}
                </div>
                <Button asChild className="mt-4 w-full justify-between">
                  <Link href={module.route}>
                    Open module
                    <ArrowUpRight className="size-4" aria-hidden="true" />
                  </Link>
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
