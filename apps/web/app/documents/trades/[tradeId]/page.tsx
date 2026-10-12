import { DocumentRegister } from "@/components/document-desk/register";
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ tradeId: string }>;
  searchParams: Promise<{ consignment?: string }>;
}) {
  const { tradeId } = await params;
  const { consignment } = await searchParams;
  return <DocumentRegister tradeId={tradeId} consignmentId={consignment} />;
}
