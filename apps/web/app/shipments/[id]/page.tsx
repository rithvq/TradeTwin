import ShipmentDetailsClient from "./shipment-details-client";

export default async function ShipmentDetailsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ShipmentDetailsClient shipmentId={id} />;
}
