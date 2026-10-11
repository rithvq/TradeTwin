import { ReceiptDesk } from "@/components/operations/receipt-desk";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ReceiptDesk id={id} />;
}
