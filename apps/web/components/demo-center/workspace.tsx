"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { DispatchJourney } from "@/components/dashboard/dispatch-journey";
import { TradeArea } from "@/components/trades/trade-context";
import { FreightRouteResult } from "@/components/freight-routes/result";
import { DISPATCH_CHANGED } from "@/lib/dispatch-dashboard";
import { enterDemo, type IntegratedDemo } from "@/lib/demo-center";
import { tradeRequest } from "@/lib/trades";
import { apiFetch, type Shipment } from "@/lib/shipments";

export function IntegratedDemoPage({ id }: { id: string }) {
  const router = useRouter();
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [journey, setJourney] = useState<
    "PICKUP_CONFIRMED" | "DEPARTED" | null
  >(null);
  const [study, setStudy] = useState("");
  const query = useQuery({
    queryKey: ["integrated-demo", id],
    queryFn: ({ signal }) =>
      tradeRequest<IntegratedDemo>(
        `/demo-sessions/${id}`,
        undefined,
        "GET",
        undefined,
        undefined,
        undefined,
        signal,
      ),
    refetchInterval: (current) =>
      ["QUEUED", "RUNNING"].includes(current.state.data?.status ?? "")
        ? 2000
        : 10000,
    retry: false,
  });
  const demo = query.data;
  const refresh = useCallback(async () => {
    await client.invalidateQueries({ queryKey: ["integrated-demo", id] });
    window.dispatchEvent(new Event(DISPATCH_CHANGED));
  }, [client, id]);
  useEffect(() => {
    if (demo?.organization_id && demo.status === "READY")
      enterDemo(id, demo.organization_id);
  }, [id, demo?.organization_id, demo?.status]);

  async function command(fresh = false) {
    setPending(true);
    setError("");
    try {
      if (fresh) {
        const value = await tradeRequest<IntegratedDemo>(
          "/demo-sessions",
          undefined,
          "POST",
          { fresh: true },
        );
        router.push(`/demo/${value.id}`);
      } else if (demo && demo.steps[demo.next_step_index]) {
        await tradeRequest(`/demo-sessions/${id}/steps`, undefined, "POST", {
          step_code: demo.steps[demo.next_step_index].code,
        });
      }
      await refresh();
    } catch (problem) {
      setError(
        problem instanceof Error ? problem.message : "Demo action unavailable",
      );
    } finally {
      setPending(false);
    }
  }
  async function originalScenario() {
    setPending(true);
    setError("");
    try {
      const shipment = await apiFetch<Shipment>("/demo/seed", {
        method: "POST",
      });
      router.push(`/shipments/${shipment.id}`);
    } catch (problem) {
      setError(
        problem instanceof Error
          ? problem.message
          : "Shipment demo unavailable",
      );
    } finally {
      setPending(false);
    }
  }
  if (query.isError)
    return (
      <main className="mx-auto max-w-5xl p-6" role="alert">
        <h1 className="text-2xl font-semibold">Demo unavailable</h1>
        <p className="my-4">{query.error.message}</p>
        <Button onClick={() => void query.refetch()}>Retry</Button>
      </main>
    );
  if (!demo)
    return (
      <p role="status" className="p-6">
        Loading demo…
      </p>
    );
  const busy = pending || ["QUEUED", "RUNNING"].includes(demo.status);
  const next = demo.steps[demo.next_step_index];
  const failure = demo.receipts.find((receipt) => receipt.status === "FAILED");
  const completed = demo.status === "READY" && !next;
  const selectedStudy = study || demo.route_study_ids.at(-1);

  const content = (
    <div className="mx-auto max-w-[1320px] space-y-6 px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="tt-kicker">SIMULATION</p>
          <h1 className="mt-2 text-3xl font-semibold">TradeTwin Demo</h1>
          <p className="mt-2 text-secondary">
            Bengaluru → Chennai · Freight, evidence and guarded dispatch
          </p>
        </div>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => void command(true)}
        >
          Start fresh demo
        </Button>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => void originalScenario()}
        >
          Original shipment scenario
        </Button>
      </header>
      {busy && (
        <p
          role="status"
          className="rounded-lg border border-line bg-soft p-4 font-medium"
        >
          {demo.next_step_index === 0 && !demo.consignment_id
            ? "Preparing encrypted documents and simulation journeys…"
            : "Running simulation step…"}{" "}
          Keep this page open or return later.
        </p>
      )}
      {(failure || error) && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-900"
        >
          {error ||
            `Demo stopped (${failure?.error_code}). Earlier records are preserved. Start a fresh demo to retry.`}
        </div>
      )}
      {demo.expired && (
        <p role="alert" className="rounded-lg border border-line bg-soft p-4">
          The demo evidence window has elapsed. Start a fresh demo to continue.
        </p>
      )}
      {demo.status !== "QUEUED" &&
        demo.status !== "RUNNING" &&
        demo.trade_id &&
        demo.consignment_id && (
          <>
            <nav
              aria-label="Demo features"
              className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
            >
              {[
                ["Commercial agreement", `/trades/${demo.trade_id}`],
                [
                  "Documents & extraction",
                  `/documents/trades/${demo.trade_id}`,
                ],
                [
                  "Freight & route optimizer",
                  `/shipments/trades/${demo.trade_id}/operations?module=Optimizer`,
                ],
                [
                  "Compliance & trace",
                  `/shipments/trades/${demo.trade_id}/operations?module=Compliance`,
                ],
                [
                  "Shipment graph",
                  `/shipments/trades/${demo.trade_id}/operations?module=Graph`,
                ],
                [
                  "Corridor intelligence",
                  `/shipments/trades/${demo.trade_id}/operations?module=Risk`,
                ],
                [
                  "Receipts & inspection",
                  `/shipments/trades/${demo.trade_id}/operations?module=Shipments`,
                ],
                ["Payments", `/shipments/trades/${demo.trade_id}/payments`],
                [
                  "Decision replay & evidence",
                  `/shipments/trades/${demo.trade_id}/operations?module=Evidence`,
                ],
                [
                  "Rule registry",
                  `/shipments/trades/${demo.trade_id}/operations?module=Regulations`,
                ],
              ].map(([label, href]) => (
                <Link
                  key={label}
                  href={href}
                  className="rounded-lg border border-line bg-surface p-4 font-semibold text-ink hover:bg-soft"
                >
                  {label} ↗
                </Link>
              ))}
            </nav>
            {demo.sample_document_version_id && (
              <Link
                className="inline-block font-medium text-primary underline underline-offset-4"
                href={`/documents/versions/${demo.sample_document_version_id}/processing`}
              >
                Open parsed sample PDF ↗
              </Link>
            )}
          </>
        )}
      <section
        aria-label="Guided demo steps"
        className="rounded-xl border border-line bg-surface p-5"
      >
        <h2 className="text-xl font-semibold">Guided journey</h2>
        <ol className="mt-4 divide-y divide-line">
          {demo.steps.map((item, index) => {
            const receipt = demo.receipts.find(
              (r) => r.step_code === item.code,
            );
            return (
              <li
                key={item.code}
                className="flex flex-wrap items-center justify-between gap-3 py-4"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium">
                    {index + 1}. {item.label}
                  </p>
                  {receipt?.result?.summary && (
                    <p className="mt-1 text-sm text-secondary">
                      {receipt.result.summary}
                    </p>
                  )}
                  {index === demo.next_step_index && (
                    <p className="mt-1 text-xs text-secondary">{item.actor}</p>
                  )}
                </div>
                <span className="text-sm font-semibold">
                  {receipt?.status === "COMPLETED"
                    ? "Completed"
                    : receipt?.status === "FAILED"
                      ? "Failed"
                      : index === demo.next_step_index
                        ? "Next"
                        : "Pending"}
                </span>
              </li>
            );
          })}
        </ol>
        {next && (
          <Button
            className="mt-4"
            disabled={
              busy || demo.status !== "READY" || demo.expired || query.isError
            }
            onClick={() => void command()}
          >
            Run next demo step
          </Button>
        )}
        {completed && (
          <p role="status" className="mt-4 font-semibold text-primary">
            Journey complete. Movement, receipt and declared payment are
            recorded.
          </p>
        )}
      </section>
      {demo.status === "READY" &&
        demo.consignment_id &&
        demo.organization_id && (
          <section className="space-y-4" aria-label="Demo dispatch control">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="mr-auto text-xl font-semibold">
                Dispatch control
              </h2>
              <Button
                variant="outline"
                onClick={() => setJourney("PICKUP_CONFIRMED")}
              >
                Pickup journey
              </Button>
              <Button variant="outline" onClick={() => setJourney("DEPARTED")}>
                Departure journey
              </Button>
            </div>
            {journey && (
              <DispatchJourney
                id={demo.consignment_id}
                action={journey}
                org={demo.organization_id}
                onClose={() => setJourney(null)}
              />
            )}
          </section>
        )}
      {demo.status === "READY" && demo.route_study_ids.length > 0 && (
        <section className="space-y-4" aria-label="Demo route comparisons">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-xl font-semibold">Route comparisons</h2>
            <label className="text-sm font-medium">
              Saved comparison
              <select
                aria-label="Demo saved comparison"
                value={selectedStudy}
                onChange={(e) => setStudy(e.target.value)}
                className="ml-3 rounded border bg-surface p-2"
              >
                {demo.route_study_ids.map((value, index) => (
                  <option key={value} value={value}>
                    {index < 2 ? "Before restriction" : "After restriction"} ·{" "}
                    {index % 2 === 0 ? "Distance priority" : "Time priority"}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {selectedStudy && (
            <FreightRouteResult key={selectedStudy} id={selectedStudy} />
          )}
        </section>
      )}
      <details className="rounded-lg border border-line bg-soft p-4 text-sm">
        <summary className="cursor-pointer font-semibold">
          Demo scope & sources
        </summary>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-secondary">
          {demo.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
          <li>
            Journey time is compressed. Corridor history contains synthetic
            driver declarations.
          </li>
        </ul>
      </details>
    </div>
  );
  return demo.organization_id && demo.status === "READY" ? (
    <TradeArea>{content}</TradeArea>
  ) : (
    <main className="tt-page">{content}</main>
  );
}
