export type RouteWeights = {
  distance: number;
  duration: number;
  road_weather_exposure: number;
  state_transit_history: number;
  toll_exposure: number;
};
export const routeFactors: Record<keyof RouteWeights, string> = {
  distance: "Distance",
  duration: "Mapped travel time",
  road_weather_exposure: "Road / weather exposure",
  state_transit_history: "Observed state-corridor delays",
  toll_exposure: "Mapped toll-road exposure",
};
export const routePresets: Record<string, RouteWeights> = {
  Balanced: {
    distance: 2000,
    duration: 3000,
    road_weather_exposure: 3000,
    state_transit_history: 1000,
    toll_exposure: 1000,
  },
  "Shorter distance": {
    distance: 7000,
    duration: 1500,
    road_weather_exposure: 1000,
    state_transit_history: 0,
    toll_exposure: 500,
  },
  "Less mapped travel time": {
    distance: 1500,
    duration: 6500,
    road_weather_exposure: 1500,
    state_transit_history: 0,
    toll_exposure: 500,
  },
  "Lower measured exposure": {
    distance: 1500,
    duration: 2000,
    road_weather_exposure: 6000,
    state_transit_history: 500,
    toll_exposure: 0,
  },
};
export type RouteTruck = {
  height_m: string;
  width_m: string;
  length_m: string;
  tare_kg: string;
  axle_load_kg: string;
  maximum_loaded_kg?: string | null;
};
export type RoadGeometry = { type: string; coordinates: unknown };
export type RouteCandidate = {
  id: string;
  label: string;
  geometry: { type: "LineString"; coordinates: number[][] };
  geometry_kind: string;
  distance_m: number;
  driving_seconds: number;
  major_road_metres: number | null;
  toll_road_metres: number | null;
  road_names: string[];
  feasibility: string;
  reason_codes: string[];
  fuel_estimate_minor?: string | null;
  metrics: Record<keyof RouteWeights, number | null>;
  nominal_arrival_at: string;
  estimated_arrival_at: string | null;
  historic_adjusted_arrival_at: string | null;
  corridor: {
    state_sequence: (string | null)[];
    state_names: string[];
    mapping_status: string;
    boundaries: {
      name: string;
      url?: string | null;
      year?: string;
      status: string;
      attribution?: string;
    };
    state_outlines: {
      state_code: string;
      name: string;
      geometry: RoadGeometry;
    }[];
  };
  history: {
    status: string;
    sample_count: number;
    median_extra_seconds: number | null;
    basis: string;
  };
  weather: {
    status: string;
    exposure: number | null;
    source_url?: string;
    method?: string;
    attribution?: string;
    samples: {
      latitude: number;
      longitude: number;
      at_unix: number;
      precipitation: number | null;
      wind_gusts_10m: number | null;
      visibility: number | null;
    }[];
  };
  provider: {
    name: string;
    url?: string;
    attribution: string;
    traffic: string;
  };
  comparison_to_best?: {
    distance_delta_m: number;
    duration_delta_seconds: number | null;
    reason_codes: string[];
  };
  state_requirements: {
    position: number;
    state_code: string | null;
    name: string;
    permit_status: string;
    published_corridor_scope: string;
  }[];
  incident_impacts: {
    outcome: string;
    headline?: string;
    source_reference?: string | null;
    effect: string;
    maximum_delay_seconds?: number | null;
  }[];
};
export type RouteStudy = {
  id: string;
  consignment_id: string;
  job_state: string;
  freshness: string;
  source_mode: string;
  execution_mode: string;
  checked_at: string | null;
  valid_until: string | null;
  error_code: string | null;
  price_visible: boolean;
  public_fingerprint_short: string | null;
  result: null | {
    engine_version: string;
    checked_at: string;
    departure_at: string;
    weights: RouteWeights;
    candidates: RouteCandidate[];
    comparison: {
      best_candidate_id: string | null;
      comparison_status: string;
      notice?: string;
      method?: string;
      active_factors: (keyof RouteWeights)[];
      omitted_factors: (keyof RouteWeights)[];
      rankings: {
        candidate_id: string;
        rank: number;
        score: number;
        pareto_member: boolean;
        contributions: {
          factor: keyof RouteWeights;
          value: number;
          unit: string;
          effective_weight_percent: number;
          weighted_loss: number;
        }[];
      }[];
    };
    provider_failures: { variant: string; code: string }[];
    policy_sources: {
      id: string;
      title: string;
      url: string;
      status: string;
      recorded_at: string;
      fingerprint_short: string;
    }[];
    policy_packs: {
      id: string;
      version: string;
      title: string;
      valid_until: string | null;
    }[];
    limitations: string[];
  };
};
export type RouteContext = {
  consignment_id: string;
  execution_mode: string;
  pins_confirmed: boolean;
  truck: RouteTruck | null;
  cargo_weight_kg: string;
  live_routing_configured: boolean;
  weather_plan: string;
  studies: {
    id: string;
    job_state: string;
    source_mode: string;
    created_at: string;
  }[];
};
export function routeWords(value: string) {
  return value.toLowerCase().replaceAll("_", " ");
}
export function routeHours(seconds: number | null) {
  return seconds === null ? "Unknown" : `${(seconds / 3600).toFixed(1)} h`;
}
