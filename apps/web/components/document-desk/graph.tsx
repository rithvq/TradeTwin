"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Background,
  Controls,
  MarkerType,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { type DocumentSummary } from "@/lib/document-desk";
import { Panel } from "./shared";

const tracks: Record<string, number> = {
  TRADE_REVISION: 0,
  CONSIGNMENT: 0,
  DOCUMENT: 1,
  DOCUMENT_VERSION: 1,
  ORIGINAL_FILE: 2,
  EXTRACTION_RUN: 3,
  FIELD_OBSERVATION: 4,
  REVIEWED_FIELD: 5,
  FACT_REVISION: 5,
  LINE_MAPPING: 6,
  MAPPING_REVISION: 6,
  FINDING: 7,
  VERIFICATION_RESULT: 7,
  ASSESSMENT_RUN: 7,
};
export function DocumentGraph({ graph }: { graph: DocumentSummary["graph"] }) {
  const [mode, setMode] = useState("Overview");
  const [selected, setSelected] = useState<string | null>(null);
  const [scope, setScope] = useState(
    graph.nodes.find((n) => n.type === "DOCUMENT")?.id ?? "",
  );
  const connected = new Set([
    selected,
    ...graph.edges
      .filter((e) => e.source === selected || e.target === selected)
      .flatMap((e) => [e.source, e.target]),
  ]);
  const { nodes, edges } = useMemo(() => {
    const scopeIds = new Set(scope ? [scope] : graph.nodes.map((n) => n.id));
    const shared = new Set(
      graph.nodes
        .filter((n) => ["TRADE_REVISION", "CONSIGNMENT"].includes(n.type))
        .map((n) => n.id),
    );
    let changed = true;
    while (changed) {
      changed = false;
      for (const edge of graph.edges)
        if (
          scopeIds.has(edge.source) &&
          !shared.has(edge.source) &&
          !scopeIds.has(edge.target)
        ) {
          scopeIds.add(edge.target);
          changed = true;
        }
    }
    for (const edge of graph.edges)
      if (scopeIds.has(edge.target) && shared.has(edge.source))
        scopeIds.add(edge.source);
    const visible = graph.nodes.filter(
      (n) =>
        scopeIds.has(n.id) &&
        (mode === "Fields" ||
          !["FIELD_OBSERVATION", "REVIEWED_FIELD", "FINDING"].includes(n.type)),
    );
    const indices: Record<number, number> = {};
    const ids = new Set(visible.map((n) => n.id));
    const nodes = visible.map((n) => {
      const track = tracks[n.type] ?? 7;
      const index = indices[track] ?? 0;
      indices[track] = index + 1;
      return {
        id: n.id,
        position: { x: track * 260, y: index * 112 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: { label: n.label },
        style: {
          width: 210,
          minHeight: 56,
          borderRadius: 4,
          fontSize: 12,
          overflowWrap: "anywhere" as const,
          background: "#fff",
          color: "#18353d",
          border: connected.has(n.id)
            ? "2px solid #087f79"
            : "1px solid #cbdade",
          opacity: selected && !connected.has(n.id) ? 0.35 : 1,
        },
      };
    });
    const edges = graph.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({
        ...e,
        type: "smoothstep",
        label:
          selected && connected.has(e.source) && connected.has(e.target)
            ? e.label
            : undefined,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: {
          stroke: "#59848d",
          opacity:
            selected && (!connected.has(e.source) || !connected.has(e.target))
              ? 0.15
              : 0.8,
        },
      }));
    return { nodes, edges };
  }, [graph, mode, selected, scope]); // eslint-disable-line react-hooks/exhaustive-deps
  const node = graph.nodes.find((n) => n.id === selected);
  return (
    <Panel title="Document provenance graph">
      <label className="text-sm">
        Document scope{" "}
        <select
          className="ml-2 rounded border border-line p-2"
          aria-label="Document graph scope"
          value={scope}
          onChange={(e) => {
            setScope(e.target.value);
            setSelected(null);
          }}
        >
          <option value="">All readable evidence</option>
          {graph.nodes
            .filter((n) => n.type === "DOCUMENT")
            .map((n) => (
              <option key={n.id} value={n.id}>
                {n.label}
              </option>
            ))}
        </select>
      </label>
      <div
        role="group"
        aria-label="Provenance graph detail"
        className="flex gap-1"
      >
        {["Overview", "Fields"].map((name) => (
          <button
            key={name}
            aria-pressed={name === mode}
            className={`rounded border px-3 py-2 text-xs ${name === mode ? "border-accent bg-teal-50 font-semibold text-accent" : "border-line text-secondary"}`}
            onClick={() => setMode(name)}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="h-[560px] min-h-96 w-full border border-line bg-surface-raised">
        <ReactFlow
          key={`${mode}:${scope}`}
          nodes={nodes}
          edges={edges}
          fitView
          minZoom={0.15}
          maxZoom={1.8}
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, n) => setSelected(n.id)}
          onPaneClick={() => setSelected(null)}
        >
          <Background color="#d5e0e4" gap={24} />
          <Controls />
        </ReactFlow>
      </div>
      {node && (
        <div className="space-y-2">
          <strong className="text-sm">{node.label}</strong>
          <p className="text-xs text-secondary">{node.type}</p>
          <Link href={node.href} className="text-sm text-accent underline">
            Open evidence source
          </Link>
        </div>
      )}
    </Panel>
  );
}
