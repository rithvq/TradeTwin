import { ConsignmentPlanner } from "@/components/operations/planner";
export default async function Page({
  params,
}: {
  params: Promise<{ tradeId: string }>;
}) {
  const { tradeId } = await params;
  return <ConsignmentPlanner tradeId={tradeId} />;
}
