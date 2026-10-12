import { notFound } from "next/navigation";
import { DocumentDesk } from "@/components/document-desk/desk";
export default async function Page({
  params,
}: {
  params: Promise<{ versionId: string; tab: string }>;
}) {
  const { versionId, tab } = await params;
  if (
    !["processing", "review", "findings", "verification", "evidence"].includes(
      tab,
    )
  )
    notFound();
  return <DocumentDesk versionId={versionId} tab={tab} />;
}
