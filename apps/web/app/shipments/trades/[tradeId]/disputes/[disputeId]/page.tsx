import { DisputeDesk } from "@/components/operations/dispute-desk";
export default async function Page({
  params,
}: {
  params: Promise<{ disputeId: string }>;
}) {
  const { disputeId } = await params;
  return <DisputeDesk id={disputeId} />;
}
