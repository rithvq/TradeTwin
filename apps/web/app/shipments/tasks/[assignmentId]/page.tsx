import { DriverTask } from "@/components/operations/driver-task";
export default async function Page({
  params,
}: {
  params: Promise<{ assignmentId: string }>;
}) {
  const { assignmentId } = await params;
  return <DriverTask id={assignmentId} />;
}
