import { DocumentMapping } from "@/components/document-desk/mapping";
export default async function Page({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  return <DocumentMapping documentId={documentId} />;
}
