"use client";
import { TradeWizard } from "@/components/trades/wizard";
import { useTradeContext } from "@/components/trades/trade-context";
export default function Page() {
  const { org, role } = useTradeContext();
  return <TradeWizard key={`${org}:${role}`} />;
}
