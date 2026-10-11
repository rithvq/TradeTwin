import { PaymentDesk } from "@/components/operations/payment-desk";
export default async function Page({
  params,
}: {
  params: Promise<{ tradeId: string }>;
}) {
  const { tradeId } = await params;
  return <PaymentDesk tradeId={tradeId} />;
}
