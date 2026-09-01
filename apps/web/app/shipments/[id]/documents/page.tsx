import DocumentUploadClient from "./document-upload-client";

export default async function ShipmentDocumentsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <DocumentUploadClient shipmentId={id} />;
}
