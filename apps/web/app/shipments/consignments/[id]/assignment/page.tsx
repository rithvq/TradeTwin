import { AssignmentDesk } from "@/components/operations/assignment";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <AssignmentDesk id={id} />;
}
