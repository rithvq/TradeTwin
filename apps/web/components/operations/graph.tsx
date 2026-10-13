"use client";
import { useId, useMemo, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { title, type Operations } from "@/lib/operations";
import { Facts } from "./shared";

const overviewLevels: Record<string, number> = {
  RFQ: 0,
  TradeTwinRun: 1,
  Candidate: 2,
  SelectionProposal: 3,
  FreightCommitment: 4,
  OperationalRoutePlan: 5,
  CommittedAssignment: 5,
  ActualDispatchEvaluation: 6,
};

const levels: Record<string, number> = {
  Trade: 0,
  Revision: 1,
  Consignment: 2,
  Schedule: 2,
  Payment: 2,
  Assignment: 3,
  Event: 3,
  Receipt: 3,
  Dispute: 3,
  Obligation: 3,
  Allocation: 3,
  vehicle_id: 4,
  driver_user_id: 4,
  ReceiptLine: 4,
  Inspection: 5,
  RFQ: 0,
  CostAssumptions: 1,
  TradeTwinRun: 2,
  Candidate: 3,
  Quote: 4,
  Route: 4,
  PlanningConstraint: 4,
  RouteDataset: 5,
  VehicleProfile: 5,
  SelectionProposal: 5,
  FreightCommitment: 6,
  OperationalRoutePlan: 7,
  CommittedAssignment: 7,
  ActualDispatchEvaluation: 8,
};
export function OperationalGraph({ graph }: { graph: Operations["graph"] }) {
  const scopeId = useId();
  const freight = graph.nodes.some((n) => n.type === "TradeTwinRun");
  const [scope, setScope] = useState(freight ? "overview" : "all");
  const [selected, setSelected] = useState<string | null>(null);
  const focused = useMemo(() => {
    if (scope === "all") return graph;
    if (scope === "overview") {
      const nodes = graph.nodes.filter((n) => n.type in overviewLevels);
      const visible = new Set(nodes.map((n) => n.id));
      return {
        nodes,
        edges: graph.edges.filter(
          (e) => visible.has(e.source) && visible.has(e.target),
        ),
      };
    }
    const roots =
      scope === "settlement"
        ? graph.nodes
            .filter((n) => ["Schedule", "Payment"].includes(n.type))
            .map((n) => n.id)
        : [scope];
    const visible = new Set(roots);
    const descendants = [...roots];
    while (descendants.length) {
      const parent = descendants.shift();
      for (const edge of graph.edges) {
        if (edge.source === parent && !visible.has(edge.target)) {
          visible.add(edge.target);
          descendants.push(edge.target);
        }
      }
    }
    const ancestors = [...roots];
    while (ancestors.length) {
      const child = ancestors.shift();
      for (const edge of graph.edges) {
        if (edge.target === child && !visible.has(edge.source)) {
          visible.add(edge.source);
          ancestors.push(edge.source);
        }
      }
    }
    return {
      nodes: graph.nodes.filter((n) => visible.has(n.id)),
      edges: graph.edges.filter(
        (e) => visible.has(e.source) && visible.has(e.target),
      ),
    };
  }, [graph, scope]);
  const typeName = (type: string) =>
    title(type.replace(/([a-z])([A-Z])/g, "$1 $2"));
  const elements = useMemo(() => {
    const rows: Record<number, number> = {};
    const nodes: Node[] = focused.nodes.map((n) => {
      const level =
        scope === "overview" ? overviewLevels[n.type] : (levels[n.type] ?? 3);
      const row = rows[level] ?? 0;
      rows[level] = row + 1;
      return {
        id: n.id,
        position: { x: level * 300, y: row * 125 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: { label: `${typeName(n.type)}: ${n.label}` },
        style: {
          width: 220,
          fontSize: 12,
          background: "var(--surface, #ffffff)",
          color: "var(--foreground, #18323a)",
          border: "1px solid #b8ccd0",
          padding: 14,
          borderRadius: 4,
        },
      };
    });
    const edges: Edge[] = focused.edges.map((e, i) => ({
      id: `${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      type: "smoothstep",
      style: { stroke: "#6e9097", strokeWidth: 1.3 },
    }));
    return { nodes, edges };
  }, [focused, scope]);
  const chosen = graph.nodes.find((n) => n.id === selected);
  const connections = graph.edges.filter(
    (e) => e.source === selected || e.target === selected,
  );
  return (
    <section className="space-y-3 py-4" aria-label="Operational relationships">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h3 className="text-lg font-semibold">Operational relationships</h3>
        <div className="min-w-0">
          <label htmlFor={scopeId} className="text-sm font-medium">
            Relationship scope
          </label>
          <select
            id={scopeId}
            className="mt-1 block max-w-full rounded border border-line bg-white p-2 text-sm"
            value={scope}
            onChange={(event) => {
              setScope(event.target.value);
              setSelected(null);
            }}
          >
            {freight && <option value="overview">Decision overview</option>}
            <option value="all">All relationships</option>
            {graph.nodes
              .filter((n) => ["Consignment", "Candidate"].includes(n.type))
              .map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label}
                </option>
              ))}
            {graph.nodes.some(
              (n) => n.type === "Schedule" || n.type === "Payment",
            ) && <option value="settlement">Goods settlement</option>}
          </select>
        </div>
      </div>
      <div className="h-[580px] min-w-0 rounded border border-line">
        <ReactFlow
          key={scope}
          nodes={elements.nodes}
          edges={elements.edges}
          fitView
          minZoom={0.1}
          nodesDraggable={false}
          onNodeClick={(_, node) => setSelected(node.id)}
          onEdgeClick={(_, edge) => setSelected(edge.source)}
          colorMode="light"
        >
          <Background gap={24} />
          <Controls />
        </ReactFlow>
      </div>
      {chosen && (
        <div className="min-w-0 space-y-2 border-t border-line py-3 text-sm">
          <strong>
            {typeName(chosen.type)}: {chosen.label}
          </strong>
          <p className="break-all text-xs text-secondary">{chosen.id}</p>
          <ul className="space-y-2">
            {connections.map((edge, index) => {
              const outgoing = edge.source === chosen.id;
              const neighbor = graph.nodes.find(
                (n) => n.id === (outgoing ? edge.target : edge.source),
              );
              return (
                <li key={index} className="flex flex-wrap items-center gap-2">
                  <span className="text-secondary">
                    {outgoing ? "Outgoing" : "Incoming"} / {typeName(edge.type)}
                  </span>
                  <button
                    type="button"
                    className="text-accent underline"
                    onClick={() => setSelected(neighbor?.id ?? null)}
                  >
                    {neighbor
                      ? `${typeName(neighbor.type)}: ${neighbor.label}`
                      : "Unavailable record"}
                  </button>
                </li>
              );
            })}
          </ul>
          {chosen.details && (
            <details open>
              <summary className="cursor-pointer font-medium">
                Record facts and sources
              </summary>
              <Facts values={chosen.details} />
            </details>
          )}
        </div>
      )}
    </section>
  );
}
