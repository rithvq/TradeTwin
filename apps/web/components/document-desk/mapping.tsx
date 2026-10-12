"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import { type DocumentRecord, type FactRevision } from "@/lib/document-desk";
import { type Operations } from "@/lib/operations";
import { type Values, displayMoney } from "@/lib/trades";
import { ErrorNotice, Panel, Status } from "./shared";

type Row = {
  document_line_ref: string;
  trade_line_ref: string;
  target_kind: string;
  consignment_item_id: string | null;
  mapped_quantity: string;
  uqc: string;
};
export function DocumentMapping({ documentId }: { documentId: string }) {
  const { org } = useTradeContext();
  const doc = useOperationsResource<DocumentRecord>(
    `/documents/${documentId}`,
    org,
  );
  const operations = useOperationsResource<Operations>(
    `/trades/${doc.data?.trade_id ?? "00000000-0000-0000-0000-000000000000"}/operations`,
    org,
  );
  const fact = useOperationsResource<FactRevision>(
    `/document-fact-revisions/${doc.data?.effective_fact_revision_id ?? "00000000-0000-0000-0000-000000000000"}`,
    org,
  );
  const history = useOperationsResource<{
    items: (Values & { mappings: Row[]; freshness: string })[];
  }>(`/documents/${documentId}/mappings`, org);
  const [rows, setRows] = useState<Row[]>([]);
  const reload = async () => {
    await doc.reload();
    await history.reload();
  };
  const mutation = useOperationalMutation(org, reload);
  useEffect(() => {
    const current = history.data?.items.find(
      (m) => m.id === doc.data?.current_mapping_revision_id,
    );
    if (current) setRows(current.mappings);
    else setRows([]);
  }, [history.data, doc.data?.current_mapping_revision_id]);
  if (doc.error) return <ErrorNotice message={doc.error} />;
  if (!doc.data) return <p>Loading document mappings...</p>;
  const lines = (fact.data?.canonical_document_json.lines ?? []) as Values[];
  const targets =
    operations.data?.consignments.flatMap((cn) =>
      cn.items.map((i) => ({ ...i, reference: cn.reference })),
    ) ?? [];
  const tradeLines = operations.data?.availability ?? [];
  return (
    <div className="space-y-5">
      <header>
        <Link
          className="text-sm text-accent underline"
          href={`/documents/versions/${doc.data.current_version_id}/review`}
        >
          Review desk
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">Document-line mappings</h1>
        <p className="mt-1 text-sm text-secondary">
          {doc.data.label} / {doc.data.execution_mode}
        </p>
      </header>
      <Panel title="Reviewed document quantities">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[450px] text-left text-sm">
            <thead>
              <tr>
                {[
                  "Description",
                  "Reviewed quantity",
                  "UQC",
                  "Mapped",
                  "Unmapped",
                ].map((h) => (
                  <th key={h} className="border-b border-line p-2">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr key={String(line.document_line_ref)}>
                  <td className="p-2">
                    {String(line.description ?? "Missing")}
                  </td>
                  <td className="p-2">{String(line.quantity ?? "Missing")}</td>
                  <td className="p-2">{String(line.uqc ?? "Missing")}</td>
                  <td className="p-2">
                    {doc.data?.mapping_summary?.find(
                      (m) => m.document_line_ref === line.document_line_ref,
                    )?.mapped_quantity ?? "0"}
                  </td>
                  <td className="p-2">
                    {doc.data?.mapping_summary?.find(
                      (m) => m.document_line_ref === line.document_line_ref,
                    )?.unmapped_quantity ?? String(line.quantity ?? "Missing")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {doc.data.canonical_document_id ? (
          <p className="text-sm">
            Alias presentation; quantity and financial aggregation are excluded.{" "}
            <Link
              className="text-accent underline"
              href={`/documents/${doc.data.canonical_document_id}/mapping`}
            >
              Canonical document
            </Link>
          </p>
        ) : (
          <p className="text-sm font-semibold">
            Document total, recorded once:{" "}
            {displayMoney(
              (fact.data?.canonical_document_json.totals as Values | undefined)
                ?.grand_total_minor,
            )}
          </p>
        )}
      </Panel>
      {!doc.data.effective_fact_revision_id && (
        <p className="text-sm text-amber-900">
          Submit reviewed quantity and UQC before confirming mappings.
        </p>
      )}
      <ErrorNotice message={mutation.error?.message ?? ""} />
      {doc.data.allowed_actions.includes("document.map") && fact.data && (
        <Panel title="Confirm mapping portions">
          <div className="space-y-3">
            {rows.map((row, index) => (
              <div
                key={index}
                className="grid min-w-0 gap-2 border-b border-line pb-3 md:grid-cols-[1fr_1.3fr_100px_70px_40px]"
              >
                <select
                  aria-label={`Document line ${index + 1}`}
                  className="min-w-0 rounded border border-line bg-white p-2 text-sm"
                  value={row.document_line_ref}
                  onChange={(e) =>
                    setRows((old) =>
                      old.map((v, i) =>
                        i === index
                          ? { ...v, document_line_ref: e.target.value }
                          : v,
                      ),
                    )
                  }
                >
                  {lines.map((l) => (
                    <option
                      key={String(l.document_line_ref)}
                      value={String(l.document_line_ref)}
                    >
                      {String(l.description ?? l.document_line_ref)}
                    </option>
                  ))}
                </select>
                <select
                  aria-label={`Mapping target ${index + 1}`}
                  className="min-w-0 rounded border border-line bg-white p-2 text-sm"
                  value={
                    row.target_kind === "ORDER_LINE"
                      ? `order:${row.trade_line_ref}`
                      : (row.consignment_item_id ?? "")
                  }
                  onChange={(e) => {
                    const target = targets.find((t) => t.id === e.target.value);
                    const order = tradeLines.find(
                      (t) => `order:${t.line_ref}` === e.target.value,
                    );
                    setRows((old) =>
                      old.map((v, i) =>
                        i === index
                          ? {
                              ...v,
                              target_kind: target
                                ? "CONSIGNMENT_ITEM"
                                : "ORDER_LINE",
                              consignment_item_id: target?.id ?? null,
                              trade_line_ref:
                                target?.line_ref ?? order?.line_ref ?? "",
                              uqc: target?.uqc ?? order?.uqc ?? "",
                            }
                          : v,
                      ),
                    );
                  }}
                >
                  {targets.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.reference} / allocated {t.allocated_quantity} {t.uqc}
                    </option>
                  ))}
                  {tradeLines.map((t) => (
                    <option key={t.line_ref} value={`order:${t.line_ref}`}>
                      Order line / {t.description}
                    </option>
                  ))}
                </select>
                <input
                  aria-label={`Mapped quantity ${index + 1}`}
                  className="min-w-0 rounded border border-line p-2 text-sm"
                  value={row.mapped_quantity}
                  inputMode="decimal"
                  onChange={(e) =>
                    setRows((old) =>
                      old.map((v, i) =>
                        i === index
                          ? { ...v, mapped_quantity: e.target.value }
                          : v,
                      ),
                    )
                  }
                />
                <span className="self-center text-xs">{row.uqc}</span>
                <Button
                  size="icon"
                  variant="outline"
                  title="Remove mapping portion"
                  aria-label={`Remove mapping ${index + 1}`}
                  onClick={() =>
                    setRows((old) => old.filter((_, i) => i !== index))
                  }
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              disabled={!lines.length || !targets.length}
              onClick={() =>
                setRows((old) => [
                  ...old,
                  {
                    document_line_ref: String(lines[0].document_line_ref),
                    trade_line_ref: targets[0].line_ref,
                    target_kind: "CONSIGNMENT_ITEM",
                    consignment_item_id: targets[0].id,
                    mapped_quantity: "",
                    uqc: targets[0].uqc,
                  },
                ])
              }
            >
              <Plus className="size-4" />
              Add mapping portion
            </Button>
            <Button
              disabled={mutation.pending || !rows.length}
              onClick={() =>
                void mutation.run(
                  `/documents/${documentId}/mapping-revisions`,
                  {
                    fact_revision_id: fact.data!.id,
                    accepted_trade_revision_id:
                      operations.data?.accepted_revision_id,
                    base_mapping_revision_id:
                      doc.data!.current_mapping_revision_id,
                    mappings: rows,
                  },
                  doc.data!.etag,
                )
              }
            >
              <Check className="size-4" />
              Confirm mapping
            </Button>
          </div>
        </Panel>
      )}
      <Panel title="Mapping history">
        {history.data?.items.map((m) => (
          <div
            key={String(m.id)}
            className="space-y-2 border-b border-line py-3"
          >
            <Status value={m.freshness} />
            <p className="break-all text-xs">Revision: {String(m.id)}</p>
            {m.mappings.map((portion, index) => (
              <p key={index} className="text-sm">
                {portion.mapped_quantity} {portion.uqc} / {portion.target_kind}
              </p>
            ))}
          </div>
        ))}
      </Panel>
    </div>
  );
}
