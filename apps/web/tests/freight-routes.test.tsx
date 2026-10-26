import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FreightRouteResult } from "@/components/freight-routes/result";
import { FreightRouteStudio } from "@/components/freight-routes/studio";
import {
  routePresets,
  type RouteCandidate,
  type RouteContext,
  type RouteStudy,
} from "@/lib/freight-routes";
import type { FreightContext } from "@/lib/freight";

const state = vi.hoisted(() => ({
  data: null as unknown,
  error: "",
  context: null as unknown,
}));
const action = vi.hoisted(() => vi.fn(async () => null));
const reload = vi.hoisted(() => vi.fn(async () => {}));
vi.mock("@/components/trades/trade-context", () => ({
  useTradeContext: () => ({ org: "seller" }),
}));
vi.mock("@/hooks/use-operations", () => ({
  useOperationsResource: (path: string) => ({
    data: path.endsWith("freight-route-intelligence")
      ? state.context
      : state.data,
    error: state.error,
    reload,
  }),
  useOperationalMutation: () => ({ run: action, pending: false, error: null }),
}));

function route(id: string, distance: number): RouteCandidate {
  return {
    id,
    label:
      id === "a" ? "Shortest mapped truck route" : "Fastest mapped truck route",
    geometry: {
      type: "LineString",
      coordinates: [
        [77.5, 13],
        [78, 13.2],
        [80, 13],
      ],
    },
    geometry_kind: "ROAD_GEOMETRY",
    distance_m: distance,
    driving_seconds: 21600,
    major_road_metres: distance,
    toll_road_metres: null,
    road_names: [id === "a" ? "NH 48" : "NH 75"],
    feasibility: "CONDITIONAL",
    reason_codes: ["LIVE_INCIDENT_COVERAGE_INCOMPLETE"],
    metrics: {
      distance,
      duration: 21600,
      road_weather_exposure: null,
      state_transit_history: null,
      toll_exposure: null,
    },
    nominal_arrival_at: "2026-10-27T14:00:00Z",
    estimated_arrival_at: null,
    historic_adjusted_arrival_at: null,
    corridor: {
      state_sequence: ["29", "33"],
      state_names: ["Karnataka", "Tamil Nadu"],
      mapping_status: "MAPPED_REFERENCE",
      boundaries: {
        name: "State reference",
        status: "REQUIRES_REVIEW",
        year: "2011",
        url: "https://www.geoboundaries.org/api.html",
      },
      state_outlines: [],
    },
    history: {
      status: "INSUFFICIENT_DATA",
      sample_count: 0,
      median_extra_seconds: null,
      basis: "Only your organization’s permitted history is used.",
    },
    weather: { status: "UNAVAILABLE", exposure: null, samples: [] },
    provider: {
      name: "ORS HGV",
      attribution: "© OpenStreetMap contributors",
      traffic: "MAP_ESTIMATE_NOT_LIVE_TRAFFIC",
    },
    state_requirements: [
      {
        position: 1,
        state_code: "29",
        name: "Karnataka",
        permit_status: "NEEDS_EVIDENCE",
        published_corridor_scope: "REQUIRES_REVIEW",
      },
    ],
    incident_impacts: [],
    comparison_to_best: {
      distance_delta_m: distance - 350000,
      duration_delta_seconds: 0,
      reason_codes: [],
    },
  };
}
function study(): RouteStudy {
  return {
    id: "study",
    consignment_id: "cn",
    job_state: "COMPLETED",
    freshness: "CURRENT",
    source_mode: "LIVE",
    execution_mode: "PRODUCTION",
    checked_at: "2026-10-27T07:00:00Z",
    valid_until: "2026-10-27T07:15:00Z",
    error_code: null,
    price_visible: false,
    public_fingerprint_short: "123456789012",
    result: {
      engine_version: "1",
      checked_at: "2026-10-27T07:00:00Z",
      departure_at: "2026-10-27T08:00:00Z",
      weights: routePresets.Balanced,
      candidates: [route("a", 350000), route("b", 370000)],
      comparison: {
        best_candidate_id: "a",
        comparison_status: "CONDITIONAL",
        active_factors: ["distance", "duration"],
        omitted_factors: ["road_weather_exposure"],
        notice: "Best among these compared routes, not a global optimum.",
        rankings: ["a", "b"].map((id, i) => ({
          candidate_id: id,
          rank: i + 1,
          score: i,
          pareto_member: true,
          contributions: [
            {
              factor: "distance",
              value: 350000 + i * 20000,
              unit: "metres",
              effective_weight_percent: 40,
              weighted_loss: i * 0.4,
            },
          ],
        })),
      },
      provider_failures: [],
      policy_sources: [
        {
          id: "s",
          title: "Official rule reference",
          url: "https://docs.ewaybillgst.gov.in/html/faq1.html",
          status: "CHANGED_REVIEW_REQUIRED",
          recorded_at: "2026-10-26T00:00:00Z",
          fingerprint_short: "123456789012",
        },
      ],
      policy_packs: [],
      limitations: ["Domestic state movement is not international customs."],
    },
  };
}
beforeEach(() => {
  state.data = study();
  state.error = "";
  action.mockClear();
});

describe("state-wise freight route comparison", () => {
  it("shows actual routes, alternatives, reasons, and missing evidence without a safety score", () => {
    render(<FreightRouteResult id="study" />);
    expect(
      screen.getByRole("img", { name: "Compared freight road routes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Freight route alternatives" }),
    ).toHaveTextContent("20.0 km versus preferred");
    expect(screen.getByText("Distance / travel")).toBeTruthy();
    expect(screen.getByText(/safety percentage/)).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "State transit requirements" }),
    ).toHaveTextContent("Karnataka → Tamil Nadu");
    fireEvent.click(
      within(screen.getByRole("table")).getByRole("button", {
        name: /^Route 2$/,
      }),
    );
    expect(screen.getByText(/Named roads: NH 75/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Official rule reference" }),
    ).toHaveAttribute("href", "https://docs.ewaybillgst.gov.in/html/faq1.html");
    expect(
      screen.queryByRole("button", {
        name: /record pickup|authorize|commit route/i,
      }),
    ).not.toBeInTheDocument();
  });
  it("removes a current preference after expiry or failed refresh", () => {
    const item = study();
    item.freshness = "STALE";
    state.data = item;
    const view = render(<FreightRouteResult id="study" />);
    expect(
      screen.queryByRole("heading", {
        name: "Preferred among compared routes",
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Historical comparison",
    );
    state.error = "network failure";
    view.rerender(<FreightRouteResult id="study" />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Current comparison unavailable",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("keeps unavailable jobs explicit", () => {
    const item = study();
    item.result = null;
    item.job_state = "FAILED";
    item.error_code = "PROVIDER_UNAVAILABLE";
    state.data = item;
    render(<FreightRouteResult id="study" />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Comparison unavailable: provider unavailable",
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
  it("requires explicit retained mode when live routing is unavailable and validates custom weights", () => {
    state.context = {
      consignment_id: "cn",
      execution_mode: "SIMULATION",
      pins_confirmed: true,
      truck: null,
      cargo_weight_kg: "400",
      live_routing_configured: false,
      weather_plan: "DISABLED",
      studies: [],
    } satisfies RouteContext;
    const freight = {
      consignment_id: "cn",
      capabilities: ["tradetwin.plan.prepare"],
      datasets: [],
    } as unknown as FreightContext;
    render(<FreightRouteStudio context={freight} />);
    expect(
      screen.getByRole("button", { name: "Compare freight routes" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Route source"), {
      target: { value: "RETAINED" },
    });
    expect(screen.getByLabelText("Retained route dataset")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Route comparison priority"), {
      target: { value: "Custom" },
    });
    fireEvent.change(screen.getByLabelText("Distance weight percent"), {
      target: { value: "99" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Weights must total 100%",
    );
    expect(
      screen.getByRole("button", { name: "Compare freight routes" }),
    ).toBeDisabled();
    expect(action).not.toHaveBeenCalled();
  });
});
