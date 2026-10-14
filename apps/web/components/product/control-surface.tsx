"use client";
import { useTradeContext } from "@/components/trades/trade-context";
import { AssuranceDesk } from "./assurance";
import { GuidedDemo } from "./demo";

export function ProductControlSurface({
  view,
}: {
  view: "assurance" | "demo";
}) {
  const { me, org } = useTradeContext();
  const capabilities =
    me.memberships
      .find((m) => m.organization_id === org)
      ?.permissions.filter((p) => !p.trade_id)
      .map((p) => p.permission_code) ?? [];
  const permitted = capabilities.includes(
    view === "assurance" ? "readiness.read" : "demo.workspace.create",
  );
  if (!permitted)
    return (
      <p className="py-6 text-secondary">
        No assigned{" "}
        {view === "assurance" ? "deployment assurance" : "demonstration"}{" "}
        capability for this organisation.
      </p>
    );
  return (
    <div className="product-controls">
      {view === "assurance" ? (
        <AssuranceDesk capabilities={capabilities} />
      ) : (
        <GuidedDemo capabilities={capabilities} />
      )}
    </div>
  );
}
