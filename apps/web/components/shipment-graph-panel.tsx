"use client";

import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
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

import {
  buildShipmentGraphElements,
  humanize,
  kindLabel,
  relationshipFamilies,
  type GraphNodeKind,
  type RelationshipFamily,
  type ShipmentFlowNode,
  type ShipmentFlowEdge,
} from "@/lib/graph/shipment-layout";

import type { ShipmentGraph } from "@/lib/shipments";
import { cn } from "@/lib/utils";

const nodeTypes: NodeTypes = { shipmentGraphNode: ShipmentGraphNodeView };

export function ShipmentGraphPanel({ graph }: { graph: ShipmentGraph }) {
  const container = useRef<HTMLDivElement>(null);
  const [flow, setFlow] = useState<ReactFlowInstance<
    ShipmentFlowNode,
    ShipmentFlowEdge
  > | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const elements = useMemo(() => buildShipmentGraphElements(graph), [graph]);
  useEffect(() => {
    if (!container.current || !flow) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        void flow.fitView({ padding: 0.16, minZoom: 0.1, maxZoom: 1 });
      });
    });
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
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
            (edge) =>
              edge.source === selectedNodeId || edge.target === selectedNodeId,
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
          label: isConnected
            ? humanize(edge.data?.relationship ?? "")
            : undefined,
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
  const selectedNode = selectedNodeId
    ? nodeById.get(selectedNodeId)
    : undefined;

  return (
    <div className="overflow-hidden rounded border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-4 py-3">
        <div
          className="flex flex-wrap gap-x-5 gap-y-2"
          aria-label="Graph node legend"
        >
          {nodeLegend.map((item) => (
            <span
              key={item.kind}
              className="flex items-center gap-2 text-xs text-secondary"
            >
              <span
                className={cn("size-2 rounded-full border", item.dotClassName)}
              />
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
            setSelectedNodeId((current) =>
              current === node.id ? null : node.id,
            )
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
          <span
            key={item.family}
            className="flex items-center gap-2 text-xs text-muted"
          >
            <span
              className={cn("h-px w-7", item.lineClassName)}
              style={
                item.dashed
                  ? { borderTopWidth: 1, borderTopStyle: "dashed" }
                  : undefined
              }
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
            <p className="mt-1 text-sm font-semibold text-ink">
              {selectedNode.data.title}
            </p>
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

function ShipmentGraphNodeView({
  data,
  selected,
}: NodeProps<ShipmentFlowNode>) {
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
        <span
          className="mt-1 block truncate text-xs font-semibold text-ink"
          title={data.title}
        >
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
      <p
        className="text-[10px] font-semibold uppercase"
        style={{ color: family.labelColor }}
      >
        {humanize(data.relationship)}
      </p>
      <p className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-secondary">
        <span className="truncate" title={data.sourceLabel}>
          {data.sourceLabel}
        </span>
        <ArrowRight className="size-3 shrink-0 text-muted" aria-hidden="true" />
        <span className="truncate" title={data.targetLabel}>
          {data.targetLabel}
        </span>
      </p>
    </li>
  );
}

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
