import { TradeWorkspace } from "@/components/trades/trade-workspace";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <TradeWorkspace tradeId={id} />;
}
