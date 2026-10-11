import { InspectionDesk } from "@/components/operations/inspection-desk";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <InspectionDesk id={id} />;
}
