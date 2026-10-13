import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import type { ReactFlowProps } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";
import { OperationalGraph } from "@/components/operations/graph";
import { ComplianceEvidenceGraph } from "@/components/compliance/evidence-graph";
import type { Operations } from "@/lib/operations";

vi.mock("@xyflow/react", () => ({
  Position: { Right: "right", Left: "left" },
  MarkerType: { ArrowClosed: "arrowclosed" },
  Background: () => null,
  Controls: () => null,
  ReactFlow: ({
    nodes = [],
    onNodeClick,
  }: Pick<ReactFlowProps, "nodes" | "onNodeClick">) => (
    <div>
      {nodes.map((node) => (
        <button
          key={node.id}
          className="react-flow__node"
          data-testid={`rf__node-${node.id}`}
          onClick={(event) => onNodeClick?.(event, node)}
        >
          {node.data.label as ReactNode}
        </button>
      ))}
    </div>
  ),
}));

const graph: Operations["graph"] = {
  nodes: [
    { id: "trade-one", type: "Trade", label: "Trade one" },
    { id: "revision-one", type: "Revision", label: "Accepted revision" },
    { id: "cn-one", type: "Consignment", label: "CN-ONE" },
    { id: "cn-two", type: "Consignment", label: "CN-TWO" },
    { id: "assignment-one", type: "Assignment", label: "Truck one" },
    { id: "assignment-two", type: "Assignment", label: "Truck two" },
  ],
  edges: [
    { source: "trade-one", target: "revision-one", type: "ACCEPTED_REVISION" },
    { source: "revision-one", target: "cn-one", type: "CONSIGNMENT" },
    { source: "revision-one", target: "cn-two", type: "CONSIGNMENT" },
    { source: "cn-one", target: "assignment-one", type: "ASSIGNMENT" },
    { source: "cn-two", target: "assignment-two", type: "ASSIGNMENT" },
  ],
};

describe("Operational graph isolation", () => {
  it("filters and inspects the operational node when another graph contains the same ID", () => {
    render(
      <>
        <ComplianceEvidenceGraph
          graph={{
            nodes: [{ id: "cn-one", type: "Consignment", label: "CN-ONE" }],
            edges: [],
          }}
        />
        <OperationalGraph graph={graph} />
      </>,
    );
    expect(screen.getAllByTestId("rf__node-cn-one")).toHaveLength(2);
    const operational = within(
      screen.getByRole("region", {
        name: "Operational relationships",
        exact: true,
      }),
    );
    fireEvent.change(operational.getByLabelText("Relationship scope"), {
      target: { value: "cn-one" },
    });
    expect(operational.getAllByTestId(/^rf__node-/)).toHaveLength(4);
    expect(
      operational.queryByTestId("rf__node-cn-two"),
    ).not.toBeInTheDocument();
    fireEvent.click(operational.getByTestId("rf__node-cn-one"));
    expect(
      operational.getByText("Incoming / Consignment", { exact: true }),
    ).toBeVisible();
    expect(
      operational.getByText("Outgoing / Assignment", { exact: true }),
    ).toBeVisible();
    expect(
      within(
        screen.getByLabelText("Compliance evidence provenance graph"),
      ).getByTestId("rf__node-cn-one"),
    ).toBeVisible();
    expect(screen.queryByText("Record: cn-one")).not.toBeInTheDocument();
  });

  it("restores all operational relationships and clears inspection when scope changes", () => {
    render(<OperationalGraph graph={graph} />);
    const operational = within(
      screen.getByRole("region", {
        name: "Operational relationships",
        exact: true,
      }),
    );
    const scope = operational.getByLabelText("Relationship scope");
    fireEvent.change(scope, { target: { value: "cn-one" } });
    fireEvent.click(operational.getByTestId("rf__node-cn-one"));
    expect(
      operational.getByText("Incoming / Consignment", { exact: true }),
    ).toBeVisible();
    fireEvent.change(scope, { target: { value: "all" } });
    expect(operational.getAllByTestId(/^rf__node-/)).toHaveLength(
      graph.nodes.length,
    );
    expect(
      operational.queryByText("Incoming / Consignment", { exact: true }),
    ).not.toBeInTheDocument();
  });
});
