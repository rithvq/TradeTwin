"use client";

import { useEffect, useMemo, useState, type ElementType } from "react";
import { ArrowRight, Link2, Pause, Play, Radio, Zap } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type TimelineNodeId = string | number;

export interface TimelineItem {
  id: TimelineNodeId;
  title: string;
  date: string;
  content: string;
  category: string;
  icon: ElementType;
  relatedIds: TimelineNodeId[];
  status: "completed" | "in-progress" | "pending";
  energy: number;
}

interface RadialOrbitalTimelineProps {
  timelineData: TimelineItem[];
  centerLabel: string;
  centerDetail?: string;
}

export default function RadialOrbitalTimeline({
  timelineData,
  centerLabel,
  centerDetail = "Digital twin",
}: RadialOrbitalTimelineProps) {
  const [activeNodeId, setActiveNodeId] = useState<TimelineNodeId | null>(
    timelineData.at(-1)?.id ?? null,
  );
  const [rotationAngle, setRotationAngle] = useState(0);
  const [autoRotate, setAutoRotate] = useState(true);

  useEffect(() => {
    if (
      !autoRotate ||
      timelineData.length < 2 ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }

    const timer = window.setInterval(() => {
      setRotationAngle((current) => Number(((current + 0.16) % 360).toFixed(2)));
    }, 50);
    return () => window.clearInterval(timer);
  }, [autoRotate, timelineData.length]);

  const activeItem = useMemo(
    () => timelineData.find((item) => item.id === activeNodeId) ?? timelineData.at(-1),
    [activeNodeId, timelineData],
  );

  function selectItem(id: TimelineNodeId) {
    setActiveNodeId(id);
    setAutoRotate(false);
  }

  return (
    <div className="overflow-hidden rounded border border-line bg-surface">
      <div className="grid lg:grid-cols-[minmax(0,1fr)_310px]">
        <div className="relative min-h-[430px] overflow-hidden sm:min-h-[560px]">
          <button
            type="button"
            onClick={() => setAutoRotate((current) => !current)}
            className="absolute right-4 top-4 z-40 flex size-10 items-center justify-center rounded border border-line bg-surface text-secondary hover:border-line hover:text-ink"
            aria-label={autoRotate ? "Pause orbital rotation" : "Resume orbital rotation"}
            title={autoRotate ? "Pause rotation" : "Resume rotation"}
          >
            {autoRotate ? (
              <Pause className="size-4" aria-hidden="true" />
            ) : (
              <Play className="size-4" aria-hidden="true" />
            )}
          </button>

          <div className="absolute left-1/2 top-1/2 aspect-square w-[94%] max-w-[540px] -translate-x-1/2 -translate-y-1/2">
            <div className="absolute left-1/2 top-1/2 aspect-square w-[78%] -translate-x-1/2 -translate-y-1/2 rounded-full border border-line" />

            <div className="absolute left-1/2 top-1/2 z-20 flex size-28 -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border border-line bg-surface px-3 text-center shadow-[0_0_42px_rgba(255,255,255,0.07)] sm:size-32">
              <Radio className="size-5 text-ink" aria-hidden="true" />
              <span className="mt-2 max-w-full truncate text-xs font-semibold text-ink">
                {centerLabel}
              </span>
              <span className="mt-1 max-w-full text-[11px] leading-4 text-muted">
                {centerDetail}
              </span>
            </div>

            {timelineData.map((item, index) => {
              const angle =
                ((index / timelineData.length) * 360 + rotationAngle - 90) % 360;
              const radians = (angle * Math.PI) / 180;
              const x = 50 + Math.cos(radians) * 33;
              const y = 50 + Math.sin(radians) * 33;
              const isActive = item.id === activeItem?.id;
              const isRelated = activeItem?.relatedIds.includes(item.id) ?? false;
              const Icon = item.icon;

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => selectItem(item.id)}
                  className="absolute z-30 flex w-24 -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center transition-[left,top,opacity] duration-700 sm:w-32"
                  style={{
                    left: `${x}%`,
                    top: `${y}%`,
                    opacity: isActive
                      ? 1
                      : Math.max(0.58, 0.78 + Math.sin(radians) * 0.15),
                  }}
                  aria-pressed={isActive}
                >
                  <span
                    className={cn(
                      "relative flex size-10 items-center justify-center rounded-full border-2 transition-all duration-300",
                      isActive
                        ? "scale-125 border-line bg-accent text-white shadow-[0_0_28px_rgba(255,255,255,0.24)]"
                        : isRelated
                          ? "border-line bg-soft text-ink tt-node-pulse"
                          : "border-line bg-surface text-secondary hover:border-line",
                    )}
                  >
                    <Icon className="size-4" aria-hidden="true" />
                  </span>
                  <span
                    className={cn(
                      "mt-3 line-clamp-2 text-xs font-semibold leading-4",
                      isActive ? "text-ink" : "text-secondary",
                    )}
                  >
                    {item.title}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <aside className="border-t border-line bg-surface p-5 lg:border-l lg:border-t-0">
          {activeItem ? (
            <Card className="border-0 bg-transparent shadow-none">
              <CardHeader className="p-0 pb-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Badge className={statusClasses(activeItem.status)}>
                    {statusLabel(activeItem.status)}
                  </Badge>
                  <span className="text-xs text-muted">{activeItem.date}</span>
                </div>
                <CardTitle className="mt-3 text-lg">{activeItem.title}</CardTitle>
                <p className="text-xs font-medium uppercase text-ink">
                  {activeItem.category}
                </p>
              </CardHeader>
              <CardContent className="p-0">
                <p className="text-sm leading-6 text-secondary">{activeItem.content}</p>

                <div className="mt-5 border-t border-line pt-4">
                  <div className="mb-2 flex items-center justify-between text-xs text-secondary">
                    <span className="flex items-center gap-2">
                      <Zap className="size-3.5" aria-hidden="true" />
                      Twin signal
                    </span>
                    <span>{Math.round(activeItem.energy)}%</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-soft">
                    <div
                      className="h-full rounded-full bg-accent transition-[width] duration-700"
                      style={{ width: `${Math.max(4, Math.min(100, activeItem.energy))}%` }}
                    />
                  </div>
                </div>

                {activeItem.relatedIds.length > 0 ? (
                  <div className="mt-5 border-t border-line pt-4">
                    <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase text-muted">
                      <Link2 className="size-3.5" aria-hidden="true" />
                      Connected events
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {activeItem.relatedIds.map((relatedId) => {
                        const relatedItem = timelineData.find((item) => item.id === relatedId);
                        return relatedItem ? (
                          <Button
                            key={relatedId}
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => selectItem(relatedId)}
                          >
                            {relatedItem.title}
                            <ArrowRight className="size-3" aria-hidden="true" />
                          </Button>
                        ) : null;
                      })}
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : (
            <p className="text-sm text-secondary">No shipment events recorded.</p>
          )}
        </aside>
      </div>
    </div>
  );
}

function statusLabel(status: TimelineItem["status"]): string {
  if (status === "completed") {
    return "Completed";
  }
  if (status === "in-progress") {
    return "Current";
  }
  return "Pending";
}

function statusClasses(status: TimelineItem["status"]): string {
  if (status === "completed") {
    return "border-emerald-300/25 bg-emerald-300/10 text-emerald-800";
  }
  if (status === "in-progress") {
    return "border-amber-300/25 bg-amber-300/10 text-amber-800";
  }
  return "border-slate-500/30 bg-slate-500/10 text-secondary";
}
