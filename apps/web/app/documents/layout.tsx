import { TradeArea } from "@/components/trades/trade-context";
export default function Layout({ children }: { children: React.ReactNode }) {
  return <TradeArea>{children}</TradeArea>;
}
