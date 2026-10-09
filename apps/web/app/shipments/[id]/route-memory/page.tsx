import RouteMemory from "@/components/route-memory";

export default async function RouteMemoryPage({params}: {params: Promise<{id: string}>}) {
  const {id} = await params;
  return <RouteMemory shipmentId={id}/>;
}
