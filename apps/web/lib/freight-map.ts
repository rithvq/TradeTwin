import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";
import type { RouteCandidate } from "./freight-routes";

export type IndiaReference = FeatureCollection<
  Polygon | MultiPolygon,
  { name: string }
>;
export type MapRoute = RouteCandidate & { positions: [number, number][] };
export const INDIA_BOUNDS: [[number, number], [number, number]] = [
  [6, 67],
  [37.5, 98],
];
export const OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const MAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>';

let reference: Promise<IndiaReference> | undefined;
export function indiaReference() {
  reference ??= fetch("/maps/india-states.geojson")
    .then(async (response) => {
      if (!response.ok) throw new Error("India map reference unavailable");
      const data = (await response.json()) as IndiaReference;
      if (data.type !== "FeatureCollection" || !data.features?.length)
        throw new Error("Invalid India map reference");
      return data;
    })
    .catch((error: unknown) => {
      reference = undefined;
      throw error;
    });
  return reference;
}
export function geographicRoutes(routes: RouteCandidate[]): MapRoute[] {
  return routes
    .filter((route) => {
      const points = route.geometry.coordinates;
      return (
        points.length >= 2 &&
        points.every(
          (p) =>
            p.length >= 2 &&
            Number.isFinite(p[0]) &&
            Number.isFinite(p[1]) &&
            Math.abs(p[0]) <= 180 &&
            Math.abs(p[1]) <= 90,
        )
      );
    })
    .map((route) => ({
      ...route,
      positions: route.geometry.coordinates.map(
        ([lon, lat]) => [lat, lon] as [number, number],
      ),
    }));
}
export function routeColor(route: RouteCandidate, selected: string) {
  return route.feasibility === "EXCLUDED"
    ? "#b45309"
    : route.id === selected
      ? "#08776e"
      : "#586f8a";
}
// Same geographic projection as the street map, scaled for the India overview.
export function overviewPoint([lon, lat]: number[]) {
  const mercator = (value: number) =>
    Math.log(Math.tan(Math.PI / 4 + (value * Math.PI) / 360));
  const north = mercator(37.5),
    south = mercator(6);
  const scale = Math.min(
    132 / (98 - 67),
    150 / (north - south) / (180 / Math.PI),
  );
  return [
    8 + (lon - 67) * scale,
    8 + (north - mercator(lat)) * (180 / Math.PI) * scale,
  ];
}
export function overviewPath(coordinates: unknown): string {
  if (!Array.isArray(coordinates) || !coordinates.length) return "";
  if (typeof coordinates[0]?.[0] === "number")
    return (
      coordinates
        .map(
          (p: number[], i: number) =>
            `${i ? "L" : "M"}${overviewPoint(p).join(",")}`,
        )
        .join(" ") + "Z"
    );
  return coordinates.map(overviewPath).join(" ");
}
