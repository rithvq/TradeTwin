"use client";
import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  MarkerType,
  type Node,
  type Edge,
} from "@xyflow/react";

export type EvidenceGraphData = {
  nodes: { id: string; type: string; label: string; content_hash?: string }[];
  edges: { source: string; target: string; relationship: string }[];
};
const columns = [
  "Source",
  "DocumentFacts",
  "Declaration",
  "LoadingManifest",
  "Verification",
  "RegulationVersion",
  "Rule",
  "Requirement",
  "Document",
  "Evaluation",
  "Review",
  "Packet",
  "Acknowledgment",
  "Authorisation",
  "ShipmentEvent",
];
const stages = [
  [
    "Source",
    "Document",
    "DocumentFacts",
    "Declaration",
    "LoadingManifest",
    "Verification",
  ],
  ["RegulationVersion", "Rule", "Requirement"],
  [
    "Evaluation",
    "Review",
    "Packet",
    "Acknowledgment",
    "Authorisation",
    "ShipmentEvent",
  ],
];
export function ComplianceEvidenceGraph({
  graph,
}: {
  graph: EvidenceGraphData;
}) {
  const requirements = graph.nodes.filter((n) => n.type === "Requirement");
  const [focus, setFocus] = useState(requirements[0]?.id ?? "ALL");
  const [inspected, setInspected] = useState<
    EvidenceGraphData["nodes"][number] | null
  >(null);
  const model = useMemo(() => {
    const visible = new Set<string>([focus]);
    if (focus === "ALL") graph.nodes.forEach((n) => visible.add(n.id));
    else {
      for (const direction of ["source", "target"] as const) {
        const search = [focus];
        const seen = new Set(search);
        while (search.length) {
          const current = search.pop()!;
          graph.edges
            .filter(
              (e) =>
                e[direction === "source" ? "target" : "source"] === current,
            )
            .forEach((e) => {
              const adjacent = e[direction];
              if (!seen.has(adjacent)) {
                seen.add(adjacent);
                search.push(adjacent);
                visible.add(adjacent);
              }
            });
        }
      }
      graph.nodes
        .filter(
          (n) =>
            n.type === "Document" &&
            graph.edges.some((e) => e.source === n.id && visible.has(e.target)),
        )
        .forEach((n) => visible.add(n.id));
    }
    const groups = new Map<number, number>();
    const nodes: Node[] = graph.nodes
      .filter((n) => visible.has(n.id))
      .sort((a, b) => columns.indexOf(a.type) - columns.indexOf(b.type))
      .map((n) => {
        const column = Math.max(
          0,
          stages.findIndex((stage) => stage.includes(n.type)),
        );
        const row = groups.get(column) ?? 0;
        groups.set(column, row + 1);
        return {
          id: n.id,
          data: {
            label: (
              <div title={n.label} className="space-y-1">
                <span className="block text-xs font-medium text-secondary">
                  {n.type}
                </span>
                <span className="block line-clamp-2 break-words font-semibold">
                  {n.label}
                </span>
              </div>
            ),
          },
          position: {
            x: column * 285,
            y: row * 115,
          },
          sourcePosition: "right" as Node["sourcePosition"],
          targetPosition: "left" as Node["targetPosition"],
          style: {
            width: 220,
            height: 88,
            background: "#fff",
            border: "1px solid #a8bac0",
            color: "#15323b",
            fontSize: 14,
            borderRadius: 4,
            whiteSpace: "pre-line",
          },
        };
      });
    const edges: Edge[] = graph.edges
      .filter((e) => visible.has(e.source) && visible.has(e.target))
      .map((e, i) => ({
        id: `provenance-${i}`,
        source: e.source,
        target: e.target,
        type: "smoothstep",
        label: e.relationship.replaceAll("_", " "),
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: "#477887" },
        labelStyle: { fontSize: 10 },
        labelBgStyle: { fill: "#f4f8f8" },
      }));
    return { nodes, edges };
  }, [graph, focus]);
  return (
    <div className="min-w-0 space-y-3">
      <label className="block text-sm font-medium">
        Requirement focus
        <select
          className="mt-1 block max-w-full rounded border p-2"
          value={focus}
          onChange={(e) => {
            setFocus(e.target.value);
            setInspected(null);
          }}
        >
          <option value="ALL">
            Complete ledger ({graph.nodes.length} records)
          </option>
          {requirements.map((n) => (
            <option key={n.id} value={n.id}>
              {n.label}
            </option>
          ))}
        </select>
      </label>
      <div
        className="min-w-0 border border-line bg-surface"
        style={{
          height: Math.max(
            560,
            Math.min(
              1300,
              Math.max(0, ...model.nodes.map((node) => node.position.y)) + 200,
            ),
          ),
        }}
        aria-label="Compliance evidence provenance graph"
      >
        <ReactFlow
          key={focus}
          nodes={model.nodes}
          edges={model.edges}
          fitView
          fitViewOptions={{ padding: 0.12, minZoom: 0.8, maxZoom: 1 }}
          minZoom={0.1}
          maxZoom={2}
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, node) =>
            setInspected(graph.nodes.find((n) => n.id === node.id) ?? null)
          }
        >
          <Background color="#a8bac0" gap={24} />
          <Controls />
        </ReactFlow>
      </div>
      {inspected && (
        <dl className="grid min-w-0 gap-2 text-sm">
          <dt className="font-semibold">
            {inspected.type}: {inspected.label}
          </dt>
          <dd className="break-all">Record: {inspected.id}</dd>
          {inspected.content_hash && (
            <dd className="break-all">SHA-256: {inspected.content_hash}</dd>
          )}
        </dl>
      )}
    </div>
  );
}
