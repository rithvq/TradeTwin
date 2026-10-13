"use client";
import { useState } from "react";
import Link from "next/link";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Fields, type FieldSpec } from "@/components/trades/fields";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationalMutation } from "@/hooks/use-operations";
import {
  ActionForm,
  Facts,
  Section,
  reason,
} from "@/components/operations/shared";
import type { ComplianceContext } from "@/lib/guarded-dispatch";
import { transportTypes } from "@/lib/guarded-dispatch";
import type { Consignment } from "@/lib/operations";
import type { Values } from "@/lib/trades";

export function TransportEvidenceDesk({
  data,
  cn,
  reload,
}: {
  data: ComplianceContext;
  cn: Consignment;
  reload: () => Promise<void>;
}) {
  const { org, me, refs } = useTradeContext();
  const mutation = useOperationalMutation(org, reload);
  const assignment = cn.assignments.find(
    (a) => a.id === cn.active_assignment_id,
  );
  const [kind, setKind] = useState("VEHICLE_RC");
  const [doc, setDoc] = useState("");
  const [states, setStates] = useState<string[]>([]);
  const [values, setValues] = useState<Values>({
    source_mode: "ORIGINAL_DOCUMENT",
    permit_basis: "UNKNOWN",
    route_restriction_position: "UNKNOWN",
  });
  const specs: FieldSpec[] = [
    { path: "document_number", label: "Record number" },
    { path: "issuing_authority", label: "Issuing authority" },
    { path: "issued_on", label: "Issued on", kind: "date" },
    { path: "valid_from", label: "Valid from (IST)", kind: "datetime" },
    {
      path: "valid_until",
      label: "Valid until, exclusive (IST)",
      kind: "datetime",
    },
    {
      path: "source_mode",
      label: "Evidence source mode",
      kind: "select",
      options: [
        "ORIGINAL_DOCUMENT",
        "ISSUER_DIGITAL_RECORD",
        "AUTHORISED_LOOKUP",
        "SELF_DECLARATION",
      ],
    },
    {
      path: "verification_result_id",
      label: "Bound authorised verification",
      kind: "select",
      options: Object.fromEntries(
        data.documents
          .find((d) => d.id === doc)
          ?.verification_results.map((r) => [
            r.id,
            `${r.check_type} / ${r.environment}`,
          ]) ?? [],
      ),
    },
    { path: "observed_at", label: "Observed at (IST)", kind: "datetime" },
    {
      path: "permit_basis",
      label: "Permit basis",
      kind: "select",
      options: [
        "NATIONAL",
        "STATE_WITH_ENDORSEMENTS",
        "TEMPORARY",
        "OTHER",
        "UNKNOWN",
      ],
    },
    {
      path: "route_restriction_position",
      label: "Route restriction position",
      kind: "select",
      options: ["NONE_DECLARED", "SUPPORTED_RESTRICTIONS", "UNKNOWN"],
    },
    {
      path: "route_restrictions",
      label: "Restrictions / unresolved interpretation",
      kind: "textarea",
    },
    {
      path: "parent_permit_evidence_revision_id",
      label: "Parent goods-permit revision",
      kind: "select",
      options: Object.fromEntries(
        data.transport_evidence
          .filter((e) => e.evidence_type === "GOODS_PERMIT")
          .map((e) => [e.id, `${e.id.slice(0, 8)} / ${e.review_outcome}`]),
      ),
    },
  ];
  if (!assignment)
    return (
      <Section name="Transport assurance">
        <p>Accepted transport assignment required</p>
      </Section>
    );
  return (
    <Section name="Transport assurance">
      <Facts
        values={{
          vehicle: assignment.vehicle_snapshot,
          assignment: assignment.id,
        }}
      />
      {data.transport_evidence.map((e) => (
        <details key={e.id}>
          <summary className="cursor-pointer text-sm font-semibold">
            {e.evidence_type} / {e.review_outcome}
          </summary>
          <Facts values={e.evidence} />
          {data.capabilities.includes("transport.evidence.review") &&
            e.can_review &&
            e.prepared_by_user_id !== me.user.id && (
              <div className="grid gap-4 sm:grid-cols-2">
                {["APPROVE_DECLARATION", "RETURN_FOR_CORRECTION"].map(
                  (decision) => (
                    <ActionForm
                      key={decision}
                      name={
                        decision === "APPROVE_DECLARATION"
                          ? "Approve transport evidence"
                          : "Return transport evidence"
                      }
                      path={`/transport-evidence-revisions/${e.id}/reviews`}
                      initial={{ decision }}
                      specs={reason}
                      reload={reload}
                    />
                  ),
                )}
              </div>
            )}
        </details>
      ))}
      {data.capabilities.includes("transport.evidence.prepare") && (
        <details>
          <summary className="cursor-pointer font-semibold">
            Prepare transport evidence revision
          </summary>
          <div className="mt-4 space-y-4">
            <Link
              className="text-sm text-accent underline"
              href={`/documents/trades/${cn.trade_id}?consignment=${cn.id}`}
            >
              Upload and review transport source
            </Link>
            <label className="block text-sm font-medium">
              Evidence slot
              <select
                className="mt-1 block w-full rounded border p-2"
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value);
                  setDoc("");
                  setValues({
                    source_mode: "ORIGINAL_DOCUMENT",
                    permit_basis: "UNKNOWN",
                    route_restriction_position: "UNKNOWN",
                  });
                }}
              >
                {transportTypes.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-medium">
              Current reviewed source
              <select
                className="mt-1 block w-full rounded border p-2"
                value={doc}
                onChange={(e) => setDoc(e.target.value)}
              >
                <option value="">Choose secured source</option>
                {data.documents
                  .filter((d) => d.document_type === kind)
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.label} /{" "}
                      {String(d.reference.document_version_id).slice(0, 8)}
                    </option>
                  ))}
              </select>
            </label>
            <Fields
              specs={specs}
              values={values}
              onChange={setValues}
              errors={mutation.error?.fields}
            />
            <fieldset className="space-y-2">
              <legend className="mb-2 text-sm font-semibold">
                States covered by the actual record
              </legend>
              <div className="grid gap-2 sm:grid-cols-3">
                {Object.entries(refs.states).map(([code, name]) => (
                  <label key={code} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={states.includes(code)}
                      onChange={() =>
                        setStates(
                          states.includes(code)
                            ? states.filter((s) => s !== code)
                            : [...states, code],
                        )
                      }
                    />
                    {name}
                  </label>
                ))}
              </div>
            </fieldset>
            {mutation.error && (
              <p role="alert">
                {mutation.error.code}: {mutation.error.message}
              </p>
            )}
            <Button
              disabled={mutation.pending || !doc}
              onClick={() =>
                void mutation.run(
                  `/consignments/${cn.id}/transport-evidence-revisions`,
                  {
                    ...values,
                    evidence_type: kind,
                    assignment_id: assignment.id,
                    subject_type:
                      kind === "DRIVER_LICENCE"
                        ? "DRIVER"
                        : kind === "CARGO_INSURANCE"
                          ? "CONSIGNMENT"
                          : "VEHICLE",
                    subject_id:
                      kind === "DRIVER_LICENCE"
                        ? assignment.driver_user_id
                        : kind === "CARGO_INSURANCE"
                          ? cn.id
                          : assignment.vehicle_id,
                    document_version_id: data.documents.find(
                      (d) => d.id === doc,
                    )?.reference.document_version_id,
                    reviewed_fact_revision_id: data.documents.find(
                      (d) => d.id === doc,
                    )?.reference.reviewed_fact_revision_id,
                    covered_vehicle_number:
                      assignment.vehicle_snapshot?.registration_number,
                    covered_driver_reference: assignment.driver_user_id,
                    covered_vehicle_classes: [
                      assignment.vehicle_snapshot?.vehicle_type,
                    ],
                    covered_states: states,
                  },
                )
              }
            >
              <Save className="size-4" />
              Record transport revision
            </Button>
          </div>
        </details>
      )}
    </Section>
  );
}
