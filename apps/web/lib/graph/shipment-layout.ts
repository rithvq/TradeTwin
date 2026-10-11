import { MarkerType, Position, type Edge, type Node } from "@xyflow/react";

import type { ShipmentGraph } from "@/lib/shipments";

export type GraphNodeKind =
  "Shipment" | "Consignment" | "RouteLeg" | "ShipmentEvent" | "Country";

export type RelationshipFamily = "structure" | "geography" | "event";

type ShipmentGraphNodeData = {
  kind: GraphNodeKind;
  title: string;
  subtitle: string;
  dimmed: boolean;
};

type ShipmentGraphEdgeData = {
  relationship: string;
  family: RelationshipFamily;
  sourceLabel: string;
  targetLabel: string;
};

export type ShipmentFlowNode = Node<ShipmentGraphNodeData, "shipmentGraphNode">;

export type ShipmentFlowEdge = Edge<ShipmentGraphEdgeData>;

type GraphElements = {
  nodes: ShipmentFlowNode[];
  edges: ShipmentFlowEdge[];
  height: number;
};

const NODE_WIDTH = 220;

const NODE_HEIGHT = 76;

export function buildShipmentGraphElements(
  graph: ShipmentGraph,
): GraphElements {
  const sourceNodes = graph.nodes;
  const nodeById = new Map(sourceNodes.map((node) => [node.id, node]));
  const events = sourceNodes.filter((node) => node.type === "ShipmentEvent");
  const shipments = sourceNodes.filter((node) => node.type === "Shipment");
  const consignments = sourceNodes.filter(
    (node) => node.type === "Consignment",
  );
  const routeLegs = sourceNodes
    .filter((node) => node.type === "RouteLeg")
    .sort(
      (left, right) => routeSequence(left.label) - routeSequence(right.label),
    );
  const countries = orderedCountries(graph);
  const knownIds = new Set(
    [...events, ...shipments, ...consignments, ...routeLegs, ...countries].map(
      (node) => node.id,
    ),
  );
  const otherNodes = sourceNodes.filter((node) => !knownIds.has(node.id));
  const operationalNodes = [...consignments, ...routeLegs, ...otherNodes];
  const operationalGap =
    consignments.length > 0 && routeLegs.length > 0 ? 46 : 0;
  const contentHeight = Math.max(
    560,
    stackSpan(events.length, 112),
    stackSpan(operationalNodes.length, 118) + operationalGap,
    stackSpan(countries.length, 174),
  );
  const height = Math.min(880, Math.max(640, contentHeight + 80));
  const positions = new Map<string, { x: number; y: number }>();

  placeStack(events, 0, 112, contentHeight, positions);
  placeStack(shipments, 305, 112, contentHeight, positions);
  placeOperationalStack(
    consignments,
    routeLegs,
    otherNodes,
    610,
    contentHeight,
    operationalGap,
    positions,
  );
  placeStack(countries, 930, 174, contentHeight, positions);

  const eventIndex = new Map(events.map((node, index) => [node.id, index]));
  const nodes: ShipmentFlowNode[] = sourceNodes.map((node) => {
    const kind = normalizeKind(node.type);
    const data = graphNodeData(node.label, kind, eventIndex.get(node.id));
    return {
      id: node.id,
      type: "shipmentGraphNode",
      data: { ...data, dimmed: false },
      position: positions.get(node.id) ?? { x: 610, y: contentHeight / 2 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      draggable: false,
      selectable: true,
      focusable: true,
      ariaLabel: `${data.subtitle}: ${data.title}`,
      style: { width: NODE_WIDTH, height: NODE_HEIGHT },
    };
  });

  const edges: ShipmentFlowEdge[] = graph.edges.map((edge) => {
    const family = relationshipFamily(edge.label);
    const familyStyle = relationshipFamilies[family];
    const isGeographic = geographicRelationships.has(edge.label);
    const sourceLabel = nodeById.get(edge.source)?.label ?? edge.source;
    const targetLabel = nodeById.get(edge.target)?.label ?? edge.target;
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: isGeographic ? "geography-source" : "primary-source",
      targetHandle: isGeographic ? "geography-target" : "primary-target",
      type: family === "geography" ? "default" : "smoothstep",
      data: {
        relationship: edge.label,
        family,
        sourceLabel,
        targetLabel,
      },
      animated: false,
      interactionWidth: 18,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 13,
        height: 13,
        color: familyStyle.stroke,
      },
      style: {
        stroke: familyStyle.stroke,
        strokeWidth: 1.25,
        strokeDasharray: familyStyle.dash,
        opacity: familyStyle.opacity,
      },
      ariaLabel: `${sourceLabel} ${humanize(edge.label)} ${targetLabel}`,
    };
  });

  return { nodes, edges, height };
}

function placeStack(
  nodes: ShipmentGraph["nodes"],
  x: number,
  gap: number,
  contentHeight: number,
  positions: Map<string, { x: number; y: number }>,
) {
  const top = Math.max(0, (contentHeight - stackSpan(nodes.length, gap)) / 2);
  nodes.forEach((node, index) =>
    positions.set(node.id, { x, y: top + index * gap }),
  );
}

function placeOperationalStack(
  consignments: ShipmentGraph["nodes"],
  routeLegs: ShipmentGraph["nodes"],
  otherNodes: ShipmentGraph["nodes"],
  x: number,
  contentHeight: number,
  sectionGap: number,
  positions: Map<string, { x: number; y: number }>,
) {
  const firstSection = consignments;
  const secondSection = [...routeLegs, ...otherNodes];
  const firstHeight = stackSpan(firstSection.length, 118);
  const secondHeight = stackSpan(secondSection.length, 118);
  let cursor = Math.max(
    0,
    (contentHeight - firstHeight - secondHeight - sectionGap) / 2,
  );
  firstSection.forEach((node, index) =>
    positions.set(node.id, { x, y: cursor + index * 118 }),
  );
  cursor += firstHeight + sectionGap;
  secondSection.forEach((node, index) =>
    positions.set(node.id, { x, y: cursor + index * 118 }),
  );
}

function stackSpan(count: number, gap: number): number {
  return count === 0 ? 0 : NODE_HEIGHT + (count - 1) * gap;
}

function orderedCountries(graph: ShipmentGraph): ShipmentGraph["nodes"] {
  const countries = graph.nodes.filter(
    (node) => node.type === "Country" || node.type === "Location",
  );
  const countryById = new Map(countries.map((node) => [node.id, node]));
  const routeLegIds = graph.nodes
    .filter((node) => node.type === "RouteLeg")
    .sort(
      (left, right) => routeSequence(left.label) - routeSequence(right.label),
    )
    .map((node) => node.id);
  const orderedIds: string[] = [];
  for (const routeLegId of routeLegIds) {
    for (const relationship of ["FROM", "TO"]) {
      const edge = graph.edges.find(
        (item) => item.source === routeLegId && item.label === relationship,
      );
      if (
        edge &&
        countryById.has(edge.target) &&
        !orderedIds.includes(edge.target)
      ) {
        orderedIds.push(edge.target);
      }
    }
  }
  for (const country of countries) {
    if (!orderedIds.includes(country.id)) {
      orderedIds.push(country.id);
    }
  }
  return orderedIds
    .map((id) => countryById.get(id))
    .filter(Boolean) as ShipmentGraph["nodes"];
}

function graphNodeData(
  label: string,
  kind: GraphNodeKind,
  eventIndex?: number,
): Omit<ShipmentGraphNodeData, "dimmed"> {
  if (kind === "Consignment") {
    const match = label.match(/^(.*) \(([^)]+)\)$/);
    return {
      kind,
      title: match?.[1] ?? label,
      subtitle: match ? `Consignment / ${humanize(match[2])}` : "Consignment",
    };
  }
  if (kind === "RouteLeg") {
    const match = label.match(/^Leg\s+(\d+):\s*(.+)$/i);
    return {
      kind,
      title: match?.[2] ?? label,
      subtitle: match ? `Route leg ${match[1]}` : "Route leg",
    };
  }
  if (kind === "ShipmentEvent") {
    return {
      kind,
      title: humanize(label),
      subtitle: `Shipment event ${String((eventIndex ?? 0) + 1).padStart(2, "0")}`,
    };
  }
  return {
    kind,
    title: label,
    subtitle: kindLabel(kind),
  };
}

function normalizeKind(type: string): GraphNodeKind {
  if (type === "Location") return "Country";
  if (
    type === "Shipment" ||
    type === "Consignment" ||
    type === "RouteLeg" ||
    type === "ShipmentEvent" ||
    type === "Country"
  ) {
    return type;
  }
  return "Consignment";
}

export function kindLabel(kind: GraphNodeKind): string {
  if (kind === "RouteLeg") {
    return "Route leg";
  }
  if (kind === "ShipmentEvent") {
    return "Shipment event";
  }
  if (kind === "Country") {
    return "Jurisdiction";
  }
  return kind;
}

function routeSequence(label: string): number {
  const match = label.match(/^Leg\s+(\d+)/i);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

function relationshipFamily(label: string): RelationshipFamily {
  if (label === "CONTAINS" || label === "HAS_ROUTE_LEG") {
    return "structure";
  }
  if (label.startsWith("AFFECTS") || label === "OCCURRED_IN") {
    return "event";
  }
  return "geography";
}

export function humanize(value: string): string {
  return value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (character) => character.toUpperCase());
}

const geographicRelationships = new Set([
  "ORIGINATES_IN",
  "DESTINED_FOR",
  "FROM",
  "TO",
  "OCCURRED_IN",
]);

export const relationshipFamilies: Record<
  RelationshipFamily,
  { stroke: string; labelColor: string; opacity: number; dash?: string }
> = {
  structure: {
    stroke: "#52656c",
    labelColor: "#273f46",
    opacity: 0.8,
  },
  geography: {
    stroke: "#08776e",
    labelColor: "#086359",
    opacity: 0.75,
    dash: "6 5",
  },
  event: {
    stroke: "#a06b09",
    labelColor: "#805008",
    opacity: 0.75,
    dash: "2 6",
  },
};
