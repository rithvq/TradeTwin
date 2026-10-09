"use client";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  Activity,
  ArrowRight,
  Boxes,
  MapPin,
  Package,
  Route,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ShipmentGraph } from "@/lib/shipments";
import { cn } from "@/lib/utils";

type GraphNodeKind = "Shipment" | "Consignment" | "RouteLeg" | "ShipmentEvent" | "Country";
type RelationshipFamily = "structure" | "geography" | "event";

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

type ShipmentFlowNode = Node<ShipmentGraphNodeData, "shipmentGraphNode">;
type ShipmentFlowEdge = Edge<ShipmentGraphEdgeData>;

type GraphElements = {
  nodes: ShipmentFlowNode[];
  edges: ShipmentFlowEdge[];
  height: number;
};

const NODE_WIDTH = 220;
const NODE_HEIGHT = 76;
const nodeTypes: NodeTypes = { shipmentGraphNode: ShipmentGraphNodeView };

export function ShipmentGraphPanel({ graph }: { graph: ShipmentGraph }) {
  const container = useRef<HTMLDivElement>(null);
  const [flow, setFlow] = useState<ReactFlowInstance<ShipmentFlowNode, ShipmentFlowEdge> | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const elements = useMemo(() => buildShipmentGraphElements(graph), [graph]);
  useEffect(() => {
    if (!container.current || !flow) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { void flow.fitView({ padding: 0.16, minZoom: 0.1, maxZoom: 1 }); });
    });
    observer.observe(container.current);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [flow, elements]);
  const nodeById = useMemo(
    () => new Map(elements.nodes.map((node) => [node.id, node])),
    [elements.nodes],
  );

  useEffect(() => {
    if (selectedNodeId && !nodeById.has(selectedNodeId)) {
      setSelectedNodeId(null);
    }
  }, [nodeById, selectedNodeId]);

  const connectedEdges = useMemo(
    () =>
      selectedNodeId
        ? elements.edges.filter(
            (edge) => edge.source === selectedNodeId || edge.target === selectedNodeId,
          )
        : [],
    [elements.edges, selectedNodeId],
  );
  const connectedNodeIds = useMemo(() => {
    const ids = new Set<string>();
    if (selectedNodeId) {
      ids.add(selectedNodeId);
      for (const edge of connectedEdges) {
        ids.add(edge.source);
        ids.add(edge.target);
      }
    }
    return ids;
  }, [connectedEdges, selectedNodeId]);

  const visibleNodes = useMemo(
    () =>
      elements.nodes.map((node) => ({
        ...node,
        selected: node.id === selectedNodeId,
        data: {
          ...node.data,
          dimmed: Boolean(selectedNodeId && !connectedNodeIds.has(node.id)),
        },
      })),
    [connectedNodeIds, elements.nodes, selectedNodeId],
  );
  const visibleEdges = useMemo(
    () =>
      elements.edges.map((edge) => {
        const isConnected = Boolean(
          selectedNodeId &&
            (edge.source === selectedNodeId || edge.target === selectedNodeId),
        );
        const family = relationshipFamilies[edge.data?.family ?? "structure"];
        return {
          ...edge,
          label: isConnected ? humanize(edge.data?.relationship ?? "") : undefined,
          style: {
            ...edge.style,
            opacity: selectedNodeId ? (isConnected ? 1 : 0.08) : family.opacity,
            strokeWidth: isConnected ? 2.2 : 1.25,
          },
          labelStyle: {
            fill: family.labelColor,
            fontSize: 10,
            fontWeight: 700,
          },
          labelBgStyle: { fill: "#ffffff", fillOpacity: 0.96 },
          labelBgPadding: [7, 4] as [number, number],
          labelBgBorderRadius: 3,
        };
      }),
    [elements.edges, selectedNodeId],
  );
  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) : undefined;

  return (
    <div className="overflow-hidden rounded border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-4 py-3">
        <div className="flex flex-wrap gap-x-5 gap-y-2" aria-label="Graph node legend">
          {nodeLegend.map((item) => (
            <span key={item.kind} className="flex items-center gap-2 text-xs text-secondary">
              <span className={cn("size-2 rounded-full border", item.dotClassName)} />
              {item.label}
            </span>
          ))}
        </div>
        <p className="text-xs text-muted">
          {elements.nodes.length} nodes / {elements.edges.length} relationships
        </p>
      </div>

      <div ref={container} style={{ height: elements.height }}>
        <ReactFlow<ShipmentFlowNode, ShipmentFlowEdge>
          nodes={visibleNodes}
          edges={visibleEdges}
          nodeTypes={nodeTypes}
          onInit={setFlow}
          fitView
          fitViewOptions={{ padding: 0.16, maxZoom: 1 }}
          minZoom={0.1}
          maxZoom={1.4}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesReconnectable={false}
          onNodeClick={(_, node) =>
            setSelectedNodeId((current) => (current === node.id ? null : node.id))
          }
          onPaneClick={() => setSelectedNodeId(null)}
          proOptions={{ hideAttribution: true }}
          aria-label="Shipment relationship graph"
        >
          <Background color="#c5d4d7" gap={28} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-2 border-t border-line px-4 py-3">
        {relationshipLegend.map((item) => (
          <span key={item.family} className="flex items-center gap-2 text-xs text-muted">
            <span
              className={cn("h-px w-7", item.lineClassName)}
              style={item.dashed ? { borderTopWidth: 1, borderTopStyle: "dashed" } : undefined}
            />
            <span className="text-secondary">{item.label}</span>
            <span>{item.detail}</span>
          </span>
        ))}
      </div>

      {selectedNode ? (
        <div className="grid gap-4 border-t border-line bg-surface px-4 py-4 md:grid-cols-[220px_minmax(0,1fr)_auto]">
          <div>
            <p className="text-[10px] font-semibold uppercase text-muted">
              {kindLabel(selectedNode.data.kind)}
            </p>
            <p className="mt-1 text-sm font-semibold text-ink">{selectedNode.data.title}</p>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {connectedEdges.map((edge) => (
              <RelationshipDetail key={edge.id} edge={edge} />
            ))}
          </ul>
          <button
            type="button"
            onClick={() => setSelectedNodeId(null)}
            className="flex size-8 items-center justify-center rounded text-muted hover:bg-soft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Clear graph focus"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function buildShipmentGraphElements(graph: ShipmentGraph): GraphElements {
  const sourceNodes = graph.nodes;
  const nodeById = new Map(sourceNodes.map((node) => [node.id, node]));
  const events = sourceNodes.filter((node) => node.type === "ShipmentEvent");
  const shipments = sourceNodes.filter((node) => node.type === "Shipment");
  const consignments = sourceNodes.filter((node) => node.type === "Consignment");
  const routeLegs = sourceNodes
    .filter((node) => node.type === "RouteLeg")
    .sort((left, right) => routeSequence(left.label) - routeSequence(right.label));
  const countries = orderedCountries(graph);
  const knownIds = new Set(
    [...events, ...shipments, ...consignments, ...routeLegs, ...countries].map(
      (node) => node.id,
    ),
  );
  const otherNodes = sourceNodes.filter((node) => !knownIds.has(node.id));
  const operationalNodes = [...consignments, ...routeLegs, ...otherNodes];
  const operationalGap = consignments.length > 0 && routeLegs.length > 0 ? 46 : 0;
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

function ShipmentGraphNodeView({ data, selected }: NodeProps<ShipmentFlowNode>) {
  const presentation = nodePresentations[data.kind];
  const Icon = presentation.icon;
  const handleStyle = {
    width: 8,
    height: 8,
    border: "2px solid #ffffff",
    background: "#52656c",
  };

  return (
    <div
      className={cn(
        "relative flex h-[76px] w-[220px] items-center gap-3 rounded border bg-surface px-3 text-left shadow-sm transition-[border-color,box-shadow,opacity]",
        presentation.borderClassName,
        data.dimmed && "opacity-65",
        selected && "border-accent shadow-[0_0_0_3px_rgba(8,119,110,0.12)]",
      )}
    >
      <Handle
        id="primary-target"
        type="target"
        position={Position.Left}
        style={{ ...handleStyle, top: "35%" }}
      />
      <Handle
        id="geography-target"
        type="target"
        position={Position.Left}
        style={{ ...handleStyle, top: "68%" }}
      />

      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded border bg-surface",
          presentation.iconClassName,
        )}
      >
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <span className="min-w-0">
        <span className="block text-[9px] font-semibold uppercase text-muted">
          {data.subtitle}
        </span>
        <span className="mt-1 block truncate text-xs font-semibold text-ink" title={data.title}>
          {data.title}
        </span>
      </span>

      <Handle
        id="primary-source"
        type="source"
        position={Position.Right}
        style={{ ...handleStyle, top: "35%" }}
      />
      <Handle
        id="geography-source"
        type="source"
        position={Position.Right}
        style={{ ...handleStyle, top: "68%" }}
      />
    </div>
  );
}

function RelationshipDetail({ edge }: { edge: ShipmentFlowEdge }) {
  const data = edge.data;
  if (!data) {
    return null;
  }
  const family = relationshipFamilies[data.family];
  return (
    <li className="min-w-0 border-l border-line pl-3">
      <p className="text-[10px] font-semibold uppercase" style={{ color: family.labelColor }}>
        {humanize(data.relationship)}
      </p>
      <p className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-secondary">
        <span className="truncate" title={data.sourceLabel}>{data.sourceLabel}</span>
        <ArrowRight className="size-3 shrink-0 text-muted" aria-hidden="true" />
        <span className="truncate" title={data.targetLabel}>{data.targetLabel}</span>
      </p>
    </li>
  );
}

function placeStack(
  nodes: ShipmentGraph["nodes"],
  x: number,
  gap: number,
  contentHeight: number,
  positions: Map<string, { x: number; y: number }>,
) {
  const top = Math.max(0, (contentHeight - stackSpan(nodes.length, gap)) / 2);
  nodes.forEach((node, index) => positions.set(node.id, { x, y: top + index * gap }));
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
  let cursor = Math.max(0, (contentHeight - firstHeight - secondHeight - sectionGap) / 2);
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
  const countries = graph.nodes.filter((node) => (node.type === "Country" || node.type === "Location"));
  const countryById = new Map(countries.map((node) => [node.id, node]));
  const routeLegIds = graph.nodes
    .filter((node) => node.type === "RouteLeg")
    .sort((left, right) => routeSequence(left.label) - routeSequence(right.label))
    .map((node) => node.id);
  const orderedIds: string[] = [];
  for (const routeLegId of routeLegIds) {
    for (const relationship of ["FROM", "TO"]) {
      const edge = graph.edges.find(
        (item) => item.source === routeLegId && item.label === relationship,
      );
      if (edge && countryById.has(edge.target) && !orderedIds.includes(edge.target)) {
        orderedIds.push(edge.target);
      }
    }
  }
  for (const country of countries) {
    if (!orderedIds.includes(country.id)) {
      orderedIds.push(country.id);
    }
  }
  return orderedIds.map((id) => countryById.get(id)).filter(Boolean) as ShipmentGraph["nodes"];
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

function kindLabel(kind: GraphNodeKind): string {
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

function humanize(value: string): string {
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

const nodePresentations: Record<
  GraphNodeKind,
  { icon: LucideIcon; borderClassName: string; iconClassName: string }
> = {
  Shipment: {
    icon: Boxes,
    borderClassName: "border-line",
    iconClassName: "border-line text-ink",
  },
  Consignment: {
    icon: Package,
    borderClassName: "border-blue-300/25",
    iconClassName: "border-blue-300/25 text-blue-800",
  },
  RouteLeg: {
    icon: Route,
    borderClassName: "border-cyan-300/25",
    iconClassName: "border-cyan-300/25 text-cyan-800",
  },
  ShipmentEvent: {
    icon: Activity,
    borderClassName: "border-amber-300/25",
    iconClassName: "border-amber-300/25 text-amber-800",
  },
  Country: {
    icon: MapPin,
    borderClassName: "border-emerald-300/25",
    iconClassName: "border-emerald-300/25 text-emerald-800",
  },
};

const relationshipFamilies: Record<
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

const nodeLegend: Array<{
  kind: GraphNodeKind;
  label: string;
  dotClassName: string;
}> = [
  { kind: "Shipment", label: "Shipment", dotClassName: "border-line bg-soft" },
  {
    kind: "Consignment",
    label: "Consignment",
    dotClassName: "border-blue-300/60 bg-blue-300/20",
  },
  {
    kind: "RouteLeg",
    label: "Route leg",
    dotClassName: "border-cyan-300/60 bg-cyan-300/20",
  },
  {
    kind: "ShipmentEvent",
    label: "Event",
    dotClassName: "border-amber-300/60 bg-amber-300/20",
  },
  {
    kind: "Country",
    label: "Jurisdiction",
    dotClassName: "border-emerald-300/60 bg-emerald-300/20",
  },
];

const relationshipLegend: Array<{
  family: RelationshipFamily;
  label: string;
  detail: string;
  lineClassName: string;
  dashed?: boolean;
}> = [
  {
    family: "structure",
    label: "Structure",
    detail: "contains / route legs",
    lineClassName: "bg-muted",
  },
  {
    family: "geography",
    label: "Geography",
    detail: "origin / destination",
    lineClassName: "border-teal-700",
    dashed: true,
  },
  {
    family: "event",
    label: "Event link",
    detail: "location / affected entity",
    lineClassName: "border-amber-700",
    dashed: true,
  },
];
