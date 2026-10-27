import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FreightRouteMap } from "@/components/freight-routes/map";
import { geographicRoutes, overviewPoint } from "@/lib/freight-map";
import type { RouteCandidate } from "@/lib/freight-routes";

vi.mock("@/components/freight-routes/map-canvas", () => ({
  FreightMapCanvas: () => <div>Map canvas</div>,
}));
function route(id: string): RouteCandidate {
  return {
    id,
    geometry_kind: "ROAD_GEOMETRY",
    feasibility: "CONDITIONAL",
    geometry: {
      type: "LineString",
      coordinates: [
        [77.5946, 12.9716],
        [78.4, 12.8],
        [80.2707, 13.0827],
      ],
    },
    provider: { attribution: "Recorded provider" },
  } as RouteCandidate;
}

describe("geographic freight map", () => {
  it("preserves every recorded point and converts longitude/latitude to the map's latitude/longitude order", () => {
    const candidate = route("a");
    const original = structuredClone(candidate.geometry);
    const mapped = geographicRoutes([candidate]);
    expect(mapped[0].positions).toEqual([
      [12.9716, 77.5946],
      [12.8, 78.4],
      [13.0827, 80.2707],
    ]);
    expect(candidate.geometry).toEqual(original);
    expect(overviewPoint([80.2707, 13.0827])[0]).toBeGreaterThan(
      overviewPoint([77.5946, 12.9716])[0],
    );
  });
  it("rejects invalid geometry rather than connecting around missing points", () => {
    const candidate = route("a");
    candidate.geometry.coordinates[1] = [NaN, 12.8];
    expect(geographicRoutes([candidate])).toEqual([]);
    render(
      <FreightRouteMap
        routes={[candidate]}
        selected="a"
        best="a"
        onSelect={() => {}}
      />,
    );
    expect(
      screen.getByText(/No geographic route coordinates/),
    ).toBeInTheDocument();
  });
  it("keeps comparison selection and visibly distinguishes simulated connections from recorded roads", () => {
    const a = route("a"),
      b = route("b");
    b.geometry_kind = "TOPOLOGICAL_SCHEMATIC";
    b.feasibility = "EXCLUDED";
    const selected = vi.fn();
    const view = render(
      <FreightRouteMap
        routes={[a, b]}
        selected="a"
        best="a"
        onSelect={selected}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Route 2 · excluded" }));
    expect(selected).toHaveBeenCalledWith("b");
    expect(screen.getByText(/recorded road geometry/)).toBeInTheDocument();
    view.rerender(
      <FreightRouteMap
        routes={[a, b]}
        selected="b"
        best="a"
        onSelect={selected}
      />,
    );
    expect(
      screen.getByText(/dashed connections are simulated/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Route 2 · excluded" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
