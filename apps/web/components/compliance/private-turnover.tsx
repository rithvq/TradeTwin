"use client";
import { useState } from "react";
import { LockKeyhole, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { Fields } from "@/components/trades/fields";
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
import type { ComplianceContext } from "@/lib/guarded-dispatch";
import type { Values } from "@/lib/trades";

type Declaration = {
  id: string;
  assessment_invoice_date: string;
  prepared_by_user_id: string;
  review_outcome: string;
};
export function PrivateTurnover({
  data,
  onSelect,
  reload,
}: {
  data: ComplianceContext;
  onSelect?: (id: string) => void;
  reload: () => Promise<void>;
}) {
  const { org, me } = useTradeContext();
  const list = useOperationsResource<{ items: Declaration[] }>(
    `/organisations/${org}/pan-turnover-declarations`,
    org,
  );
  const [pan, setPan] = useState("");
  const [identity, setIdentity] = useState("");
  const [values, setValues] = useState<Values>({
    assessment_invoice_date: new Date().toLocaleDateString("en-CA", {
      timeZone: "Asia/Kolkata",
    }),
    supplier_exclusion_code: "UNKNOWN",
    history_completeness_declared: false,
  });
  const [years, setYears] = useState<
    Record<
      string,
      {
        existence_status: string;
        pan_aggregate_turnover_minor: string;
        source_document_version_ids: string[];
      }
    >
  >({});
  const [selected, setSelected] = useState("");
  const preview = useOperationsResource<Values>(
    `/pan-turnover-declarations/${selected || "00000000-0000-0000-0000-000000000000"}`,
    org,
  );
  const mutation = useOperationalMutation(org, async () => {
    await list.reload();
    await reload();
  });
  const canPrepare = data.capabilities.includes("turnover.prepare");
  const invoiceDate = String(values.assessment_invoice_date ?? ""),
    year = Number(invoiceDate.slice(0, 4)),
    fy = Number(invoiceDate.slice(5, 7)) >= 4 ? year : year - 1;
  const expectedYears = Array.from(
    { length: Math.max(0, Math.min(84, fy - 2017)) },
    (_, index) => String(index + 2017),
  );
  return (
    <Section name="Private seller PAN turnover">
      <p className="flex items-center gap-2 text-sm font-medium">
        <LockKeyhole className="size-4" />
        Seller-only encrypted declarations
      </p>
      {list.error && <p role="alert">{list.error}</p>}
      <label className="block text-sm font-medium">
        Existing declaration
        <select
          className="mt-1 block w-full rounded border p-2"
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            if (e.target.value) onSelect?.(e.target.value);
          }}
        >
          <option value="">Select declaration</option>
          {list.data?.items.map((d) => (
            <option key={d.id} value={d.id}>
              {d.assessment_invoice_date} / {d.review_outcome} /{" "}
              {d.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      {selected && preview.data && (
        <details>
          <summary className="cursor-pointer font-medium">
            Private declaration history and derived conclusions
          </summary>
          <Facts values={preview.data} />
        </details>
      )}
      {selected &&
        data.capabilities.includes("turnover.review") &&
        list.data?.items.find((d) => d.id === selected)?.prepared_by_user_id !==
          me.user.id && (
          <ActionForm
            name="Approve turnover declaration"
            path={`/pan-turnover-declarations/${selected}/reviews`}
            initial={{ decision: "APPROVE_DECLARATION" }}
            specs={reason}
            reload={async () => {
              await list.reload();
              await reload();
            }}
          />
        )}
      {data.capabilities.includes("turnover.review") &&
        selected &&
        list.data?.items.find((d) => d.id === selected)?.prepared_by_user_id !==
          me.user.id && (
          <ActionForm
            name="Return turnover declaration"
            path={`/pan-turnover-declarations/${selected}/reviews`}
            initial={{ decision: "RETURN_FOR_CORRECTION" }}
            specs={reason}
            reload={async () => {
              await list.reload();
              await reload();
            }}
          />
        )}
      {canPrepare && (
        <details>
          <summary className="cursor-pointer font-semibold">
            Prepare a new private declaration
          </summary>
          <div className="mt-4 space-y-4">
            <label className="block text-sm font-medium">
              PAN
              <input
                type="password"
                autoComplete="off"
                maxLength={10}
                className="mt-1 block w-full rounded border p-2"
                value={pan}
                onChange={(e) => setPan(e.target.value.toUpperCase())}
              />
            </label>
            <Button
              variant="outline"
              disabled={mutation.pending || pan.length !== 10}
              onClick={async () => {
                const result = await mutation.run<{ id: string }>(
                  `/organisations/${org}/private-pan-identities`,
                  { pan, reason: "Seller-provided private PAN identity" },
                );
                if (result) {
                  setIdentity(result.id);
                  setPan("");
                }
              }}
            >
              <LockKeyhole className="size-4" />
              Encrypt PAN identity
            </Button>
            {identity && (
              <p className="text-sm text-accent">Encrypted identity recorded</p>
            )}
            <Fields
              specs={[
                {
                  path: "assessment_invoice_date",
                  label: "Assessment invoice date",
                  kind: "date",
                },
                {
                  path: "supplier_exclusion_code",
                  label: "Supplier exclusion position",
                  kind: "select",
                  options: ["NONE_CLAIMED", "UNKNOWN"],
                },
                {
                  path: "history_completeness_declared",
                  label: "Complete PAN-level preceding-year history declared",
                  kind: "boolean",
                },
                {
                  path: "declaration_note",
                  label: "Declaration source and limitations",
                  kind: "textarea",
                },
              ]}
              values={values}
              onChange={setValues}
              errors={mutation.error?.fields}
            />
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    <th className="p-2">Financial year</th>
                    <th className="p-2">Existence</th>
                    <th className="p-2">PAN aggregate turnover (paise)</th>
                    <th className="p-2">Reviewed source</th>
                  </tr>
                </thead>
                <tbody>
                  {expectedYears.map((key) => {
                    const row = years[key] ?? {
                      existence_status: "UNKNOWN",
                      pan_aggregate_turnover_minor: "",
                      source_document_version_ids: [],
                    };
                    function update(patch: Partial<typeof row>) {
                      setYears({ ...years, [key]: { ...row, ...patch } });
                    }
                    return (
                      <tr key={key}>
                        <td className="p-2 whitespace-nowrap">
                          {key}-{String(Number(key) + 1).slice(2)}
                        </td>
                        <td className="p-2">
                          <select
                            aria-label={`Existence ${key}`}
                            className="rounded border p-2"
                            value={row.existence_status}
                            onChange={(e) =>
                              update({
                                existence_status: e.target.value,
                                pan_aggregate_turnover_minor: "",
                              })
                            }
                          >
                            {[
                              "UNKNOWN",
                              "IN_EXISTENCE",
                              "NOT_IN_EXISTENCE",
                            ].map((s) => (
                              <option key={s}>{s}</option>
                            ))}
                          </select>
                        </td>
                        <td className="p-2">
                          <input
                            aria-label={`PAN aggregate turnover ${key}`}
                            inputMode="numeric"
                            className="w-full min-w-32 rounded border p-2"
                            disabled={row.existence_status !== "IN_EXISTENCE"}
                            value={row.pan_aggregate_turnover_minor}
                            onChange={(e) =>
                              update({
                                pan_aggregate_turnover_minor: e.target.value,
                              })
                            }
                          />
                        </td>
                        <td className="p-2">
                          <select
                            aria-label={`Turnover source ${key}`}
                            value={row.source_document_version_ids[0] ?? ""}
                            onChange={(e) =>
                              update({
                                source_document_version_ids: e.target.value
                                  ? [e.target.value]
                                  : [],
                              })
                            }
                            className="max-w-48 rounded border p-2"
                          >
                            <option value="">No source selected</option>
                            {data.private_turnover_sources.map((d) => (
                              <option
                                key={d.id}
                                value={String(d.reference.document_version_id)}
                              >
                                {d.label}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {mutation.error && <p role="alert">{mutation.error.message}</p>}
            <Button
              disabled={!identity || mutation.pending}
              onClick={async () => {
                const result = await mutation.run<{ id: string }>(
                  `/organisations/${org}/pan-turnover-declarations`,
                  {
                    ...values,
                    schema_version: 1,
                    pan_identity_reference: identity,
                    relevant_financial_years: expectedYears.map((key) => {
                      const row = years[key];
                      return {
                        financial_year_start: Number(key),
                        existence_status: row?.existence_status ?? "UNKNOWN",
                        pan_aggregate_turnover_minor:
                          row?.existence_status === "IN_EXISTENCE" &&
                          row.pan_aggregate_turnover_minor
                            ? row.pan_aggregate_turnover_minor
                            : null,
                        source_document_version_ids:
                          row?.source_document_version_ids ?? [],
                        provenance: row?.source_document_version_ids.length
                          ? "REVIEWED_RECORD"
                          : "SELF_DECLARED",
                      };
                    }),
                  },
                );
                if (result) {
                  setSelected(result.id);
                  onSelect?.(result.id);
                }
              }}
            >
              <Save className="size-4" />
              Record private declaration
            </Button>
          </div>
        </details>
      )}
    </Section>
  );
}
