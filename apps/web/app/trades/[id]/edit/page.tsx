import { TradeWizard } from "@/components/trades/wizard";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <TradeWizard key={id} tradeId={id} />;
}
