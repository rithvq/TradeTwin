"use client";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { Facts, Section } from "@/components/operations/shared";
import type { Values } from "@/lib/trades";

export function CommittedRoute({ consignmentId }: { consignmentId: string }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<{ route_plan_json: Values }>(
    `/consignments/${consignmentId}/route-plan`,
    org,
  );
  if (resource.error) return <p role="alert">{resource.error}</p>;
  if (!resource.data) return null;
  const plan = resource.data.route_plan_json;
  const route = plan.route_snapshot as Values;
  return (
    <Section name="Committed road route">
      <Facts
        values={{
          corridor: plan.state_sequence,
          pickup_at: plan.planned_pickup_at,
          departure_at: plan.planned_departure_at,
          estimated_arrival_at: plan.estimated_arrival_at,
          distance_m: route.distance_meters,
          route_nodes: route.ordered_node_keys,
          route_segments: route.ordered_edge_keys,
          limitations: route.limitations,
        }}
      />
    </Section>
  );
}
