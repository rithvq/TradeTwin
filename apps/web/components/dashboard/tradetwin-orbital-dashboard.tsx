"use client";

import { Activity } from "lucide-react";
import {
  type CSSProperties,
  type KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { DashboardSummary } from "@/components/dashboard/dashboard-summary";
import { MobileModuleGrid } from "@/components/dashboard/mobile-module-grid";
import {
  OrbitalModuleCard,
  StatusBadge,
} from "@/components/dashboard/orbital-module-card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { DashboardSummaryData, TradeTwinModule } from "@/types/dashboard";

type OrbitStyle = CSSProperties & {
  "--node-angle"?: string;
  "--node-counter-angle"?: string;
};

export function TradeTwinOrbitalDashboard({
  modules,
  summary,
  isLoading = false,
}: {
  modules: TradeTwinModule[];
  summary: DashboardSummaryData;
  isLoading?: boolean;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isPageVisible, setIsPageVisible] = useState(true);
  const reducedMotion = useReducedMotion();
  const nodeRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const selectedModule = useMemo(
    () => modules.find((module) => module.id === selectedId) ?? null,
    [modules, selectedId],
  );
  const relatedIds = useMemo(
    () => new Set(selectedModule?.relatedIds ?? []),
    [selectedModule],
  );
  const selectedIndex = selectedModule
    ? modules.findIndex((module) => module.id === selectedModule.id)
    : -1;
  const selectedBaseAngle = selectedIndex >= 0 ? -90 + selectedIndex * (360 / modules.length) : 0;
  const focusRotation = selectedIndex >= 0 ? -145 - selectedBaseAngle : 0;
  const orbitPaused = reducedMotion || !isPageVisible || selectedModule !== null;

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectedId(null);
      }
    };
    const onVisibilityChange = () => setIsPageVisible(!document.hidden);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  function handleNodeKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const isPrevious = event.key === "ArrowLeft" || event.key === "ArrowUp";
    const isNext = event.key === "ArrowRight" || event.key === "ArrowDown";
    if (!isPrevious && !isNext && event.key !== "Home" && event.key !== "End") {
      return;
    }
    event.preventDefault();
    const nextIndex =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? modules.length - 1
          : (index + (isPrevious ? -1 : 1) + modules.length) % modules.length;
    nodeRefs.current[nextIndex]?.focus();
  }

  return (
    <main className="tt-dashboard-page">
      <section
        data-testid="dashboard-shell"
        className="tt-dashboard-shell relative w-full px-4 pb-6 pt-5 sm:px-6 md:p-0"
        aria-label="TradeTwin dashboard"
      >
        <div className="mb-5 flex flex-col items-start gap-3 md:hidden">
          <div>
            <p className="tt-kicker">Command center</p>
            <h1 id="dashboard-title-mobile" className="mt-1 text-2xl font-semibold text-ink">
              Compliance digital twin
            </h1>
          </div>
          <StatusBadge
            status={summary.platformStatus === "operational" ? "operational" : "attention"}
          />
        </div>

        <div
          data-testid="dashboard-workspace"
          className="tt-dashboard-workspace hidden grid-cols-1 border border-line bg-surface md:grid"
        >
          <div
            data-testid="orbit-stage"
            className={cn(
              "tt-orbit-stage relative min-w-0 overflow-hidden",
              orbitPaused && "tt-orbit-paused",
              selectedModule && "tt-orbit-has-selection",
            )}
            onClick={(event) => {
              const target = event.target as Element;
              if (!target.closest("[data-orbit-interactive]")) {
                setSelectedId(null);
              }
            }}
          >
            <div className="absolute left-6 top-5 z-10 flex items-center gap-2 text-xs text-secondary">
              <Activity className="size-3.5 text-ink" aria-hidden="true" />
              {isLoading ? "Synchronizing services" : `Updated ${formatRefreshTime(summary.refreshedAt)}`}
            </div>

            <div
              className="tt-dashboard-orbit-shell absolute top-1/2 z-10"
              aria-label="TradeTwin module orbit"
            >
              <div
                data-testid="main-orbit"
                className="tt-main-orbit absolute rounded-full border"
                aria-hidden="true"
              />
              <div
                data-testid="orbit-center"
                className="tt-orbit-center absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2"
                aria-hidden="true"
              />

              <div
                data-testid="orbit-track"
                data-auto-rotate={orbitPaused ? "false" : "true"}
                className={cn(
                  "tt-orbit-track absolute inset-0",
                  !orbitPaused && "tt-orbit-spin",
                )}
                style={selectedModule ? { transform: `rotate(${focusRotation}deg)` } : undefined}
              >
                {modules.map((module, index) => {
                  const Icon = module.icon;
                  const baseAngle = -90 + index * (360 / modules.length);
                  const isSelected = selectedId === module.id;
                  const isRelated = relatedIds.has(module.id);
                  const isFaded = Boolean(selectedModule && !isSelected && !isRelated);
                  const nodeStyle: OrbitStyle = {
                    "--node-angle": `${baseAngle}deg`,
                    "--node-counter-angle": `${-baseAngle}deg`,
                  };

                  return (
                    <div
                      key={module.id}
                      className="tt-orbit-node-position absolute left-1/2 top-1/2"
                      style={{ transform: `rotate(${baseAngle}deg) translateX(var(--tt-orbit-radius))` }}
                    >
                      <div
                        className={cn(
                          "tt-orbit-node-upright",
                          !orbitPaused && "tt-orbit-counter-spin",
                        )}
                        style={
                          orbitPaused
                            ? { transform: `rotate(${-baseAngle - focusRotation}deg)` }
                            : nodeStyle
                        }
                      >
                        <div className="tt-orbit-node-anchor h-[86px] w-[108px]">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <button
                                ref={(element) => {
                                  nodeRefs.current[index] = element;
                                }}
                                type="button"
                                data-orbit-interactive
                                data-module-id={module.id}
                                data-related={isRelated ? "true" : "false"}
                                aria-label={`Open ${module.title} details`}
                                aria-describedby={`module-description-${module.id}`}
                                aria-pressed={isSelected}
                                onClick={() => setSelectedId(module.id)}
                                onKeyDown={(event) => handleNodeKeyDown(event, index)}
                                className={cn(
                                  "tt-orbit-node group/node flex h-[86px] w-[108px] flex-col items-center gap-2 rounded text-center transition-[opacity,transform,filter] duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-4 focus-visible:ring-offset-surface",
                                  isSelected && "tt-orbit-node-selected scale-110",
                                  isRelated && "tt-orbit-node-related",
                                  isFaded && "opacity-70 saturate-50",
                                )}
                              >
                                <span
                                  className="relative flex size-12 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-ink shadow-[0_8px_30px_rgba(0,0,0,0.72)] transition-colors group-hover/node:border-line group-hover/node:bg-soft group-hover/node:text-ink"
                                >
                                  <Icon className="size-5" aria-hidden="true" />
                                </span>
                                <span className="max-w-[108px] text-xs font-semibold leading-4 text-ink">
                                  {module.shortTitle}
                                </span>
                                <span id={`module-description-${module.id}`} className="sr-only">
                                  {module.description}
                                </span>
                              </button>
                            </TooltipTrigger>
                            <TooltipContent>{module.title}</TooltipContent>
                          </Tooltip>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

            </div>

            {selectedModule ? (
              <OrbitalModuleCard
                module={selectedModule}
                modules={modules}
                onClose={() => setSelectedId(null)}
              />
            ) : null}
          </div>
        </div>

        <MobileModuleGrid modules={modules} />
      </section>

      <DashboardSummary summary={summary} />
    </main>
  );
}

function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updatePreference = () => setReducedMotion(mediaQuery.matches);
    updatePreference();
    mediaQuery.addEventListener("change", updatePreference);
    return () => mediaQuery.removeEventListener("change", updatePreference);
  }, []);

  return reducedMotion;
}

function formatRefreshTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "just now"
    : parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
