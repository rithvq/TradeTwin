import { TradeArea } from "@/components/trades/trade-context";
import { ProductControlSurface } from "@/components/product/control-surface";

export default function DemonstrationPage() {
  return (
    <TradeArea>
      <ProductControlSurface view="demo" />
    </TradeArea>
  );
}
