"use client";

import { ArrowUpRight, CircleDot, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { TradeTwinModule } from "@/types/dashboard";

export function OrbitalModuleCard({
  module,
  modules,
  onClose,
}: {
  module: TradeTwinModule;
  modules: TradeTwinModule[];
  onClose: () => void;
}) {
  const router = useRouter();
  const Icon = module.icon;
  const relatedModules = modules.filter((item) => module.relatedIds.includes(item.id));

  return (
    <aside
      data-orbit-interactive
      aria-label={`${module.title} details`}
      className="tt-orbital-detail absolute right-4 top-1/2 z-30 w-[min(330px,42vw)] -translate-y-1/2 overflow-hidden rounded border border-line bg-surface/95 p-5 shadow-2xl backdrop-blur-xl"
    >
      <div className="absolute inset-x-0 top-0 h-px bg-soft" />
      <button
        type="button"
        onClick={onClose}
        className="absolute right-3 top-3 flex size-8 items-center justify-center rounded text-muted transition-colors hover:bg-soft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        aria-label={`Close ${module.title} details`}
      >
        <X className="size-4" aria-hidden="true" />
      </button>

      <div className="flex items-start gap-3 pr-8">
        <span className="flex size-11 shrink-0 items-center justify-center rounded border border-line bg-soft text-ink">
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase text-muted">Control module</p>
          <h2 className="mt-1 text-xl font-semibold text-ink">{module.title}</h2>
        </div>
      </div>

      <StatusBadge status={module.status} className="mt-4" />
      <p className="mt-4 text-sm leading-6 text-secondary">{module.description}</p>

      {module.metric ? (
        <div className="mt-5 flex items-end justify-between border-y border-line py-4">
          <div>
            <p className="text-xs font-medium text-muted">Current metric</p>
            <p className="mt-1 text-sm text-secondary">{module.metric.label}</p>
          </div>
          <div className="text-right">
            <p className="text-3xl font-semibold text-ink">{module.metric.value}</p>
            {module.metric.isMock ? (
              <p className="mt-1 text-xs text-violet-800">Demo value</p>
            ) : (
              <p className="mt-1 text-xs text-emerald-800">Live</p>
            )}
          </div>
        </div>
      ) : null}

      <div className="mt-5 space-y-2">
        <p className="text-xs font-semibold uppercase text-muted">Quick actions</p>
        {module.quickActions.map((action) => (
          <Button key={action.route} asChild variant="outline" className="w-full justify-between">
            <Link href={action.route}>
              {action.label}
              <ArrowUpRight className="size-4" aria-hidden="true" />
            </Link>
          </Button>
        ))}
      </div>

      <Button
        type="button"
        className="mt-4 w-full justify-between"
        onClick={() => router.push(module.route)}
      >
        Open module
        <ArrowUpRight className="size-4" aria-hidden="true" />
      </Button>

      <div className="mt-5 border-t border-line pt-4">
        <p className="text-xs font-semibold uppercase text-muted">Related modules</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {relatedModules.map((related) => (
            <Link
              key={related.id}
              href={related.route}
              className="inline-flex items-center gap-1.5 rounded border border-line bg-soft px-2.5 py-1.5 text-xs font-medium text-secondary transition-colors hover:border-line hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <CircleDot className="size-3 text-ink" aria-hidden="true" />
              {related.shortTitle}
            </Link>
          ))}
        </div>
      </div>
    </aside>
  );
}

export function StatusBadge({
  status,
  className,
}: {
  status: TradeTwinModule["status"];
  className?: string;
}) {
  const statusConfig = {
    operational: {
      label: "Operational",
      className: "border-emerald-300/25 bg-emerald-300/10 text-emerald-800",
      dot: "bg-emerald-300",
    },
    attention: {
      label: "Attention required",
      className: "border-amber-300/25 bg-amber-300/10 text-amber-800",
      dot: "bg-amber-300",
    },
    prototype: {
      label: "Prototype",
      className: "border-violet-300/25 bg-violet-300/10 text-violet-800",
      dot: "bg-violet-300",
    },
    unavailable: {
      label: "Unavailable",
      className: "border-red-300/25 bg-red-300/10 text-red-800",
      dot: "bg-red-300",
    },
  }[status];

  return (
    <Badge className={cn(statusConfig.className, className)}>
      <span className={cn("mr-1.5 size-1.5 rounded-full", statusConfig.dot)} />
      {statusConfig.label}
    </Badge>
  );
}
