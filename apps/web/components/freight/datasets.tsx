"use client";
import { useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import {
  ActionForm,
  Facts,
  Section,
  reason,
} from "@/components/operations/shared";
import type { Values } from "@/lib/trades";

export function RoutingDataDesk() {
  const { me, org } = useTradeContext();
  const permissions =
    me.memberships
      .find((m) => m.organization_id === org)
      ?.permissions.map((p) => p.permission_code) ?? [];
  return permissions.includes("routing.dataset.read") ? (
    <DatasetRecords permissions={permissions} />
  ) : null;
}
function DatasetRecords({ permissions }: { permissions: string[] }) {
  const { org } = useTradeContext();
  const resource = useOperationsResource<{
    items: {
      id: string;
      content_hash: string;
      status: string;
      dataset_json: Values;
    }[];
  }>("/routing/dataset-revisions", org);
  const mutation = useOperationalMutation(org, resource.reload);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  return (
    <Section name="Reviewed routing datasets and planning policies">
      {permissions.includes("routing.dataset.prepare") && (
        <form
          className="flex flex-wrap items-center gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!file) return;
            try {
              const data: unknown = JSON.parse(await file.text());
              await mutation.run("/routing/dataset-revisions", data);
            } catch {
              setError("A valid routing dataset JSON record is required.");
            }
          }}
        >
          <label className="text-sm font-medium">
            Dataset revision
            <input
              aria-label="Routing dataset JSON"
              className="ml-3 text-sm"
              type="file"
              accept="application/json,.json"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <Button disabled={!file || mutation.pending}>
            <Upload className="size-4" />
            Prepare retained dataset
          </Button>
        </form>
      )}
      {(error || resource.error || mutation.error) && (
        <p role="alert">{error || resource.error || mutation.error?.message}</p>
      )}
      {resource.data?.items.map((d) => (
        <details key={d.id} className="border-b py-3">
          <summary className="cursor-pointer font-medium">
            {String(d.dataset_json.dataset_code)} /{" "}
            {String(d.dataset_json.version)} / {d.status}
          </summary>
          <Facts
            values={{
              source: d.dataset_json.source_reference,
              validity: d.dataset_json.valid_until,
              licensing: d.dataset_json.license_reference,
              retention: d.dataset_json.retention_policy,
              coverage: d.dataset_json.supported_state_codes,
              planning_policy: d.dataset_json.planning_policy,
              limitations: d.dataset_json.limitations,
            }}
          />
          {permissions.includes("routing.dataset.review") && (
            <ActionForm
              name="Approve dataset review"
              path={`/routing/dataset-revisions/${d.id}/review-approvals`}
              initial={{ content_hash: d.content_hash }}
              specs={reason}
              reload={resource.reload}
            />
          )}
          {permissions.includes("routing.dataset.publish") && (
            <>
              <ActionForm
                name="Publish exact dataset"
                path={`/routing/dataset-revisions/${d.id}/publications`}
                initial={{ content_hash: d.content_hash }}
                specs={reason}
                reload={resource.reload}
              />
              <ActionForm
                name="Suspend dataset"
                path={`/routing/dataset-revisions/${d.id}/suspensions`}
                initial={{ content_hash: d.content_hash }}
                specs={reason}
                reload={resource.reload}
              />
            </>
          )}
        </details>
      ))}
    </Section>
  );
}
