import { IntegratedDemoPage } from "@/components/demo-center/workspace";

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <IntegratedDemoPage key={id} id={id} />;
}
