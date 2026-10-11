import { OperationsWorkspace } from "@/components/operations/workspace";
export default async function Page({
  params,
}: {
  params: Promise<{ tradeId: string }>;
}) {
  const { tradeId } = await params;
  return <OperationsWorkspace tradeId={tradeId} />;
}
