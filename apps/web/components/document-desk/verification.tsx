"use client";
import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDocumentVersion } from "@/hooks/use-document-desk";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import { type Values } from "@/lib/trades";
import { InputLabel } from "./register";
import { ErrorNotice, Panel, Status } from "./shared";

export function VerificationPanel({
  desk,
}: {
  desk: ReturnType<typeof useDocumentVersion>;
}) {
  const { doc, fact, version, org } = desk;
  const capabilities = useOperationsResource<{
    checks: { check_type: string; availability: string }[];
    limitations: string[];
  }>("/verification-capabilities", org);
  const [target, setTarget] = useState("parties.supplier.gstin");
  const [checkType, setCheckType] = useState("GSTIN_AUTHORITY_LOOKUP");
  const [identifier, setIdentifier] = useState("");
  const [portal, setPortal] = useState("https://services.gst.gov.in/");
  const [observed, setObserved] = useState("");
  const [time, setTime] = useState("");
  const [connection, setConnection] = useState("");
  const connections = useOperationsResource<{ items: Values[] }>(
    `/organizations/${org}/verification-connections`,
    org,
  );
  const mutation = useOperationalMutation(org, desk.reload);
  const attestations = useOperationsResource<{ items: Values[] }>(
    `/document-versions/${version?.id ?? "00000000-0000-0000-0000-000000000000"}/manual-attestations`,
    org,
  );
  if (!doc || !version) return null;
  return (
    <Panel title="Independent verification checks">
      <InputLabel text="Authorised connection">
        <select
          value={connection}
          onChange={(e) => setConnection(e.target.value)}
        >
          <option value="">No configured connection</option>
          {connections.data?.items.map((c) => (
            <option key={String(c.id)} value={String(c.id)}>
              {String(c.adapter_name)} / {String(c.provider_environment)}
            </option>
          ))}
        </select>
      </InputLabel>
      <InputLabel text="Identifier field">
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
          {[
            "parties.supplier.gstin",
            "parties.recipient.gstin",
            "header.irn",
            "eway_bill.eway_bill_number",
          ].map((path) => (
            <option key={path}>{path}</option>
          ))}
        </select>
      </InputLabel>
      <ErrorNotice message={mutation.error?.message ?? capabilities.error} />
      {!!attestations.data?.items.length && (
        <details>
          <summary className="text-sm font-semibold">
            Manual portal observation history
          </summary>
          {attestations.data.items.map((a) => (
            <div
              key={String(a.id)}
              className="border-b border-line py-3 text-sm"
            >
              <Status value="MANUAL_REPORTED" />
              <p>
                {String(a.check_type)} / {String(a.observed_status)}
              </p>
              <p className="text-secondary">
                {String(a.observed_at)} / {String(a.portal_source_url)}
              </p>
            </div>
          ))}
        </details>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {capabilities.data?.checks.map((capability) => {
          const checks = doc.verification_checks.filter(
            (c) => c.check_type === capability.check_type,
          );
          const latest = checks.at(-1)?.results.at(-1);
          const result = latest?.result_json;
          return (
            <article
              key={capability.check_type}
              className="space-y-3 rounded border border-line p-4"
            >
              <h3 className="text-sm font-semibold">
                {capability.check_type.replaceAll("_", " ")}
              </h3>
              <div className="flex flex-wrap gap-2">
                <Status value={capability.availability} />
                {latest && <Status value={latest.freshness} />}
              </div>
              {result && (
                <>
                  <dl className="grid grid-cols-2 gap-2 text-xs">
                    {[
                      "signature_integrity",
                      "issuer_trust",
                      "lookup_outcome",
                      "identifier_match",
                      "certificate_revocation_status",
                      "provider_environment",
                    ].map((key) => (
                      <div key={key}>
                        <dt className="text-secondary">
                          {key.replaceAll("_", " ")}
                        </dt>
                        <dd className="mt-1 font-medium">
                          {String(result[key])}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <p className="break-all text-xs text-secondary">
                    Checked at: {String(result.checked_at)}
                  </p>
                  <p className="break-all text-xs">
                    Covered fields:{" "}
                    {((result.covered_field_paths ?? []) as string[]).join(
                      ", ",
                    ) || "None"}
                  </p>
                  {(result.limitations as string[]).map((limit) => (
                    <p key={limit} className="text-xs text-secondary">
                      {limit}
                    </p>
                  ))}
                </>
              )}
              {!latest && checks.length > 0 && (
                <p className="text-xs text-secondary">Check queued / running</p>
              )}
              {doc.allowed_actions.includes("document.verify.request") && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={mutation.pending}
                  onClick={async () => {
                    const r = await mutation.run<{ job_id: string }>(
                      `/document-versions/${version.id}/verification-checks`,
                      {
                        check_type: capability.check_type,
                        connection_id: connection || null,
                        fact_revision_id: fact?.id ?? null,
                        target_field_path: [
                          "GSTIN_FORMAT",
                          "GSTIN_AUTHORITY_LOOKUP",
                          "IRN_LIVE_STATUS",
                          "EWB_AUTHORITY_LOOKUP",
                        ].includes(capability.check_type)
                          ? capability.check_type === "IRN_LIVE_STATUS"
                            ? "header.irn"
                            : capability.check_type === "EWB_AUTHORITY_LOOKUP"
                              ? "eway_bill.eway_bill_number"
                              : target.endsWith(".gstin")
                                ? target
                                : "parties.supplier.gstin"
                          : null,
                      },
                    );
                    if (r) desk.watchJob(r.job_id);
                  }}
                >
                  <ShieldCheck className="size-4" />
                  Request check
                </Button>
              )}
            </article>
          );
        })}
      </div>
      {doc.allowed_actions.includes("document.manual_attestation.record") && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            Manual portal observation
          </summary>
          <form
            className="mt-3 grid gap-3 sm:grid-cols-2"
            onSubmit={async (e) => {
              e.preventDefault();
              await mutation.run(
                `/document-versions/${version.id}/manual-attestations`,
                {
                  check_type: checkType,
                  target_identifier: identifier,
                  portal_source_url: portal,
                  observed_at: new Date(time).toISOString(),
                  observed_status: observed,
                  evidence_attachment_ids: [],
                },
              );
            }}
          >
            <InputLabel text="Observation type">
              <select
                value={checkType}
                onChange={(e) => setCheckType(e.target.value)}
              >
                {[
                  "GSTIN_AUTHORITY_LOOKUP",
                  "IRN_LIVE_STATUS",
                  "EWB_AUTHORITY_LOOKUP",
                ].map((kind) => (
                  <option key={kind}>{kind}</option>
                ))}
              </select>
            </InputLabel>
            <InputLabel text="Observed identifier">
              <input
                required
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
              />
            </InputLabel>
            <InputLabel text="Official portal">
              <input
                required
                type="url"
                value={portal}
                onChange={(e) => setPortal(e.target.value)}
              />
            </InputLabel>
            <InputLabel text="Observation time">
              <input
                required
                type="datetime-local"
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
            </InputLabel>
            <InputLabel text="Reported status">
              <input
                required
                value={observed}
                onChange={(e) => setObserved(e.target.value)}
              />
            </InputLabel>
            <Button variant="outline" disabled={mutation.pending}>
              Record manual observation
            </Button>
          </form>
          <p className="mt-2 text-xs text-secondary">
            MANUAL_REPORTED / Portal observation reported by reviewer
          </p>
        </details>
      )}
      <ConnectionSetup org={org} />
    </Panel>
  );
}
function ConnectionSetup({ org }: { org: string }) {
  const connections = useOperationsResource<{ items: Values[] }>(
    `/organizations/${org}/verification-connections`,
    org,
  );
  const [binding, setBinding] = useState("");
  const [environment, setEnvironment] = useState("LIVE");
  const mutation = useOperationalMutation(org, connections.reload);
  if (connections.error) return null;
  return (
    <details>
      <summary className="cursor-pointer text-sm font-semibold">
        Authorised read-only provider connections
      </summary>
      <form
        className="mt-3 grid gap-3 sm:grid-cols-2"
        onSubmit={async (e) => {
          e.preventDefault();
          await mutation.run(`/organizations/${org}/verification-connections`, {
            adapter_name: "AUTHORISED_READ_ONLY_V1",
            provider_environment: environment,
            authorised_secret_binding: binding,
            allowed_check_types: [
              "GSTIN_AUTHORITY_LOOKUP",
              "IRN_LIVE_STATUS",
              "EWB_AUTHORITY_LOOKUP",
            ],
          });
        }}
      >
        <InputLabel text="Pre-authorised secret binding">
          <input
            required
            value={binding}
            onChange={(e) => setBinding(e.target.value)}
            autoComplete="off"
          />
        </InputLabel>
        <InputLabel text="Provider environment">
          <select
            value={environment}
            onChange={(e) => setEnvironment(e.target.value)}
          >
            {["LIVE", "SANDBOX", "SIMULATION"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </InputLabel>
        <Button variant="outline" disabled={mutation.pending}>
          Connect provider
        </Button>
      </form>
      <ErrorNotice message={mutation.error?.message ?? ""} />
      {connections.data?.items.map((c) => (
        <p key={String(c.id)} className="mt-2 text-xs">
          {String(c.adapter_name)} / {String(c.provider_environment)} /{" "}
          {String(c.status)}
        </p>
      ))}
    </details>
  );
}
