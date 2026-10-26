"use client";

import { useEffect, useState } from "react";
import { type DispatchJourney, dispatchLabel } from "@/lib/dispatch-dashboard";
import { DispatchFacts, DispatchStatus } from "./dispatch-panel-shared";
import { displayTime } from "@/lib/trades";

export function DispatchValidity({ journey }: { journey: DispatchJourney }) {
  const authorization = journey.stages.find((stage) => stage.number === 5);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const received = performance.now();
    setElapsed(0);
    const timer = window.setInterval(
      () => setElapsed(performance.now() - received),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [journey.checked_at]);
  const expires = authorization?.facts.expires_at;
  const remaining = expires
    ? Math.max(
        0,
        Math.ceil(
          (Date.parse(String(expires)) -
            Date.parse(journey.checked_at) -
            elapsed) /
            1000,
        ),
      )
    : null;
  const detail = journey.validity;
  const inputGroups = [
    { label: "Start inputs", inputs: detail.start_inputs },
    { label: "Expiry inputs", inputs: detail.expiry_inputs },
    {
      label: "Evaluation evidence deadlines",
      inputs: detail.evaluation_deadlines,
    },
  ];
  return (
    <article
      aria-labelledby="dispatch-validity-title"
      className="rounded-lg border border-line p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 id="dispatch-validity-title" className="font-semibold text-ink">
          5. Validity
        </h4>
        <DispatchStatus value={authorization?.status ?? "NOT_ISSUED"} />
      </div>
      {authorization && <DispatchFacts facts={authorization.facts} />}
      {remaining !== null && (
        <p
          data-testid="dispatch-countdown"
          className="mt-3 text-sm font-medium tabular-nums"
        >
          {remaining
            ? `${Math.floor(remaining / 60)}m ${remaining % 60}s until the recorded window ends`
            : "Recorded window ended"}
        </p>
      )}
      <p className="mt-2 text-xs text-secondary">
        Countdown is informational. Server time controls permission; expiry is
        exclusive.
      </p>
      {detail.detail_status !== "RECORDED" ? (
        <p className="mt-3 text-sm">{detail.notice}</p>
      ) : (
        <>
          <p className="mt-4 text-sm">
            <strong>Window limited by:</strong>{" "}
            {detail.expiry_limited_by?.map(dispatchLabel).join(", ")}
          </p>
          <p className="mt-2 text-sm text-secondary">
            Start limited by:{" "}
            {detail.start_limited_by?.map(dispatchLabel).join(", ")}
          </p>
          <details className="mt-4 text-sm">
            <summary className="cursor-pointer font-medium">
              Inputs recorded at issuance
            </summary>
            {inputGroups.map(({ label, inputs }) => (
              <div key={label} className="mt-3">
                <h5 className="font-medium">{label}</h5>
                <ul className="mt-2 space-y-2">
                  {inputs?.map((input, index) => (
                    <li
                      key={`${input.code}:${index}`}
                      className="flex flex-wrap justify-between gap-2"
                    >
                      <span className="capitalize text-secondary">
                        {dispatchLabel(input.code)}
                      </span>
                      <span>{displayTime(input.at)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </details>
        </>
      )}
    </article>
  );
}
