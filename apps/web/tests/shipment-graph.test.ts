import { describe, expect, it } from "vitest";

import { buildShipmentGraphElements } from "@/components/shipment-graph-panel";
import type { ShipmentGraph } from "@/lib/shipments";

const graph: ShipmentGraph = {
  nodes: [
    { id: "shipment:1", label: "TT-DEMO", type: "Shipment" },
    { id: "consignment:1", label: "Batteries (UAE_TRANSIT)", type: "Consignment" },
    { id: "route:1", label: "Leg 1: India to UAE", type: "RouteLeg" },
    { id: "event:1", label: "LOADED", type: "ShipmentEvent" },
    { id: "country:uae", label: "UAE", type: "Country" },
    { id: "country:india", label: "India", type: "Country" },
  ],
  edges: [
    {
      id: "shipment:contains:consignment",
      source: "shipment:1",
      target: "consignment:1",
      label: "CONTAINS",
    },
    {
      id: "shipment:route:route",
      source: "shipment:1",
      target: "route:1",
      label: "HAS_ROUTE_LEG",
    },
    {
      id: "route:from:india",
      source: "route:1",
      target: "country:india",
      label: "FROM",
    },
    {
      id: "route:to:uae",
      source: "route:1",
      target: "country:uae",
      label: "TO",
    },
    {
      id: "event:affects:consignment",
      source: "event:1",
      target: "consignment:1",
      label: "AFFECTS_CONSIGNMENT",
    },
    {
      id: "event:occurred:india",
      source: "event:1",
      target: "country:india",
      label: "OCCURRED_IN",
    },
  ],
};

describe("shipment graph layout", () => {
  it("preserves every graph node and relationship", () => {
    const result = buildShipmentGraphElements(graph);

    expect(result.nodes.map((node) => node.id).sort()).toEqual(
      graph.nodes.map((node) => node.id).sort(),
    );
    expect(result.edges.map((edge) => edge.id).sort()).toEqual(
      graph.edges.map((edge) => edge.id).sort(),
    );
    expect(result.edges.map((edge) => edge.data?.relationship).sort()).toEqual(
      graph.edges.map((edge) => edge.label).sort(),
    );
  });

  it("uses distinct, forward visual stages without overlapping nodes", () => {
    const result = buildShipmentGraphElements(graph);
    const nodeById = new Map(result.nodes.map((node) => [node.id, node]));
    const event = nodeById.get("event:1");
    const shipment = nodeById.get("shipment:1");
    const consignment = nodeById.get("consignment:1");
    const route = nodeById.get("route:1");
    const country = nodeById.get("country:india");

    expect(event!.position.x).toBeLessThan(shipment!.position.x);
    expect(shipment!.position.x).toBeLessThan(consignment!.position.x);
    expect(consignment!.position.x).toBeLessThan(country!.position.x);
    expect(route!.position.x).toBe(consignment!.position.x);

    const positions = result.nodes.map(
      (node) => `${node.position.x}:${node.position.y}`,
    );
    expect(new Set(positions).size).toBe(result.nodes.length);
  });

  it("orders jurisdictions using the route-leg sequence", () => {
    const result = buildShipmentGraphElements(graph);
    const india = result.nodes.find((node) => node.id === "country:india");
    const uae = result.nodes.find((node) => node.id === "country:uae");

    expect(india!.position.y).toBeLessThan(uae!.position.y);
  });
});
