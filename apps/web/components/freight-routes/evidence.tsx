import { displayTime } from "@/lib/trades";
import {
  routeHours,
  routeWords,
  type RouteCandidate,
  type RouteStudy,
} from "@/lib/freight-routes";

function SourceLink({
  url,
  children,
}: {
  url?: string | null;
  children: React.ReactNode;
}) {
  return url?.startsWith("https://") ? (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="text-accent underline"
    >
      {children}
    </a>
  ) : (
    <span>{children}</span>
  );
}

export function FreightRouteEvidence({
  candidate,
  study,
}: {
  candidate: RouteCandidate;
  study: RouteStudy;
}) {
  return (
    <div className="space-y-4">
      <section
        aria-label="State transit requirements"
        className="rounded-lg border border-line p-4"
      >
        <h4 className="font-semibold text-ink">State-wise transit evidence</h4>
        <p className="mt-2 text-sm text-secondary">
          {candidate.corridor.state_names.length
            ? candidate.corridor.state_names.join(" → ")
            : "The full state corridor could not be confirmed."}
        </p>
        <ol className="mt-4 flex flex-wrap gap-3">
          {candidate.state_requirements.map((state, i) => (
            <li
              key={i}
              className="min-w-[150px] flex-1 rounded-md border border-line bg-soft p-3 text-sm"
            >
              <strong>
                {state.position}. {state.name}
              </strong>
              <p className="mt-2 capitalize text-secondary">
                Permit: {routeWords(state.permit_status)}
              </p>
              <p className="mt-1 capitalize text-secondary">
                Policy scope: {routeWords(state.published_corridor_scope)}
              </p>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-secondary">
          Boundary reference:{" "}
          <SourceLink url={candidate.corridor.boundaries.url}>
            {candidate.corridor.boundaries.name}
          </SourceLink>
          {candidate.corridor.boundaries.year
            ? ` · represented year ${candidate.corridor.boundaries.year}`
            : ""}
          . {routeWords(candidate.corridor.mapping_status)}. Map boundaries do
          not establish legal clearance.
        </p>
      </section>
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-line p-4">
          <h4 className="font-semibold text-ink">Observed corridor memory</h4>
          <p className="mt-2 text-sm">
            {candidate.history.sample_count} matching completed journeys ·
            median excess {routeHours(candidate.history.median_extra_seconds)}
          </p>
          <details className="mt-2 text-xs text-secondary">
            <summary className="cursor-pointer">History basis</summary>
            <p className="mt-2">{candidate.history.basis}</p>
          </details>
        </section>
        <section className="rounded-lg border border-line p-4">
          <h4 className="font-semibold text-ink">Forecasts and road data</h4>
          <p className="mt-2 text-sm capitalize">
            {routeWords(candidate.weather.status)}
          </p>
          <p className="mt-2 text-xs">
            <SourceLink url={candidate.weather.source_url}>
              {candidate.weather.attribution ?? "No weather source confirmed"}
            </SourceLink>
          </p>
          {!!candidate.weather.samples.length && (
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer font-medium">
                Route-time forecast samples
              </summary>
              {candidate.weather.method && (
                <p className="mt-2 text-secondary">
                  {candidate.weather.method}
                </p>
              )}
              <ol className="mt-2 space-y-2">
                {candidate.weather.samples.map((sample, i) => (
                  <li key={i}>
                    {displayTime(new Date(sample.at_unix * 1000).toISOString())}
                    : rain {sample.precipitation ?? "Unknown"} mm · gusts{" "}
                    {sample.wind_gusts_10m ?? "Unknown"} km/h · visibility{" "}
                    {sample.visibility ?? "Unknown"} m
                  </li>
                ))}
              </ol>
            </details>
          )}
        </section>
      </div>
      {!!candidate.incident_impacts.length && (
        <section className="rounded-lg border border-line p-4">
          <h4 className="font-semibold text-ink">
            Restrictions and operational reports
          </h4>
          <ul className="mt-3 space-y-3 text-sm">
            {candidate.incident_impacts.map((impact, i) => (
              <li key={i}>
                <strong>{impact.headline ?? routeWords(impact.effect)}</strong>
                <p className="capitalize text-secondary">
                  {routeWords(impact.outcome)} ·{" "}
                  <SourceLink url={impact.source_reference}>
                    Source record
                  </SourceLink>
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
      <details className="rounded-lg border border-line p-4">
        <summary className="cursor-pointer font-semibold text-ink">
          Policy sources and comparison limits
        </summary>
        <ul className="mt-3 space-y-3 text-sm">
          {study.result?.policy_sources.map((source) => (
            <li key={source.id}>
              <SourceLink url={source.url}>{source.title}</SourceLink>
              <p className="mt-1 capitalize text-secondary">
                {routeWords(source.status)}
              </p>
              <p className="mt-1 text-xs text-secondary">
                Reference recorded {displayTime(source.recorded_at)} ·{" "}
                {source.fingerprint_short}
              </p>
            </li>
          ))}
        </ul>
        <ul className="mt-4 list-disc space-y-2 pl-5 text-xs text-secondary">
          {study.result?.limitations.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
