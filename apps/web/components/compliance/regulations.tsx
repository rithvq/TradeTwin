"use client";
import { useState } from "react";
import { BookOpen, FlaskConical, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { Fields } from "@/components/trades/fields";
import {
  ActionForm,
  Facts,
  Section,
  reason,
} from "@/components/operations/shared";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import { tradeRequest, type Values } from "@/lib/trades";
import type { Attachment } from "@/lib/operations";
import { Status } from "@/components/document-desk/shared";
import { RuleExpression, type Expression } from "./rule-expression";
import { EvidenceUpload } from "@/components/operations/evidence-upload";

type Pack = {
  id: string;
  title: string;
  content_hash: string;
  publication_state: string;
  environment: string;
  created_by_user_id: string;
  effective_from: string;
  effective_until: string | null;
  policy_json: Values;
  rules: { id: string; rule_json: Values }[];
  test_runs?: Values[];
  publication_events?: Values[];
};
type Registry = {
  sources: Values[];
  source_conflicts: Values[];
  items: Pack[];
};
export function RegulationsDesk({
  attachments = [],
  tradeId,
  reload,
}: {
  attachments?: Attachment[];
  tradeId?: string;
  reload?: () => Promise<void>;
}) {
  const { org, me } = useTradeContext();
  const registry = useOperationsResource<Registry>(
    "/regulations/supported-scope",
    org,
  );
  const mutation = useOperationalMutation(org, registry.reload);
  const permissions =
    me.memberships.find((m) => m.organization_id === org)?.permissions ?? [];
  const can = (p: string) => permissions.some((g) => g.permission_code === p);
  const [source, setSource] = useState<Values>({
    source_kind: "RULE",
    retrieved_at: new Date().toISOString(),
    source_origin: "OFFICIAL_SNAPSHOT_PROVIDED",
  });
  const [sources, setSources] = useState<string[]>([]);
  const [draft, setDraft] = useState<Values | null>(null);
  const [error, setError] = useState("");
  const [environment, setEnvironment] = useState("PRODUCTION");
  return (
    <div className="space-y-5">
      <Section name="Versioned rule registry">
        {registry.error && <p role="alert">{registry.error}</p>}
        {registry.data?.items.map((pack) => (
          <details key={pack.id} className="border-b py-3">
            <summary className="cursor-pointer font-semibold">
              {pack.title} / {pack.environment} / {pack.publication_state}
            </summary>
            <Facts
              values={{
                pack_hash: pack.content_hash,
                effective_from: pack.effective_from,
                effective_until: pack.effective_until,
                policy: pack.policy_json,
              }}
            />
            <Section name="Publication history">
              {pack.publication_events?.map((entry) => (
                <p key={String(entry.id)} className="text-sm">
                  {String(entry.event_type)} / {String(entry.created_at)} /{" "}
                  {String(entry.reason)}
                </p>
              ))}
            </Section>
            {can("regulation.pack.review") &&
              pack.created_by_user_id === me.user.id && (
                <p className="text-sm text-amber-900">
                  The author cannot review or publish this pack.
                </p>
              )}
            <div className="space-y-3">
              {pack.rules.map((rule) => (
                <details key={rule.id}>
                  <summary className="cursor-pointer text-sm font-medium">
                    {String(rule.rule_json.rule_code)} /{" "}
                    {String(rule.rule_json.class)}
                  </summary>
                  <Facts values={rule.rule_json} />
                </details>
              ))}
            </div>
            {pack.test_runs?.map((test) => (
              <details key={String(test.id)}>
                <summary className="cursor-pointer text-sm font-medium">
                  Registered tests: {String(test.status)}
                </summary>
                <Facts values={test.results_json as Values} />
              </details>
            ))}
            {can("regulation.pack.test") && (
              <ActionForm
                name="Run registered boundary tests"
                path={`/regulations/rule-pack-revisions/${pack.id}/test-runs`}
                initial={{
                  pack_hash: pack.content_hash,
                  test_suite_id: "PH4_REQUIRED_BOUNDARIES_V1",
                }}
                reload={registry.reload}
              />
            )}
            {can("regulation.pack.review") &&
              pack.created_by_user_id !== me.user.id &&
              pack.test_runs?.find((r) => r.status === "PASSED") && (
                <ActionForm
                  name="Independently approve exact pack"
                  path={`/regulations/rule-pack-revisions/${pack.id}/review-approvals`}
                  initial={{
                    pack_hash: pack.content_hash,
                    passed_test_run_id: pack.test_runs.find(
                      (r) => r.status === "PASSED",
                    )!.id,
                  }}
                  specs={reason}
                  reload={registry.reload}
                />
              )}
            {can("regulation.pack.publish") &&
              pack.created_by_user_id !== me.user.id &&
              pack.publication_events?.find(
                (r) => r.event_type === "REVIEW_APPROVED",
              ) && (
                <ActionForm
                  name="Publish independently reviewed version"
                  path={`/regulations/rule-pack-revisions/${pack.id}/publications`}
                  initial={{
                    pack_hash: pack.content_hash,
                    review_approval_event_id: pack.publication_events.find(
                      (r) => r.event_type === "REVIEW_APPROVED",
                    )!.id,
                  }}
                  reload={registry.reload}
                />
              )}
            {can("regulation.pack.suspend") &&
              pack.publication_state === "PUBLISHED" && (
                <ActionForm
                  name="Suspend rule pack"
                  path={`/regulations/rule-pack-revisions/${pack.id}/suspensions`}
                  specs={reason}
                  reload={registry.reload}
                />
              )}
          </details>
        ))}
      </Section>
      <Section name="Source register">
        {registry.data?.sources.map((s) => (
          <article key={String(s.id)} className="border-b py-3">
            <a
              className="font-medium text-accent underline"
              href={String(s.official_url)}
              target="_blank"
              rel="noreferrer"
            >
              {String(s.title)}
            </a>
            <Facts
              values={{
                kind: s.source_kind,
                source_hash: s.source_sha256,
                metadata: s.source_json,
              }}
            />
          </article>
        ))}
        {can("regulation.source.register") && (
          <details>
            <summary className="cursor-pointer font-semibold">
              Register secured official source snapshot
            </summary>
            <div className="mt-4 space-y-4">
              {tradeId && reload && (
                <EvidenceUpload
                  tradeId={tradeId}
                  consignments={[]}
                  records={[]}
                  reload={reload}
                  purposeOverride="OTHER"
                />
              )}
              <Fields
                specs={[
                  {
                    path: "source_kind",
                    label: "Source kind",
                    kind: "select",
                    options: [
                      "ACT",
                      "RULE",
                      "NOTIFICATION",
                      "CIRCULAR",
                      "PORTAL_ADVISORY",
                      "OFFICIAL_API_CONTRACT",
                    ],
                  },
                  {
                    path: "source_status",
                    label: "Source lifecycle",
                    kind: "select",
                    options: ["UNKNOWN", "ACTIVE", "HELD", "WITHDRAWN"],
                  },
                  { path: "issuer", label: "Issuer" },
                  { path: "title", label: "Source title" },
                  { path: "official_url", label: "Official HTTPS URL" },
                  {
                    path: "document_number",
                    label: "Notification / document number",
                  },
                  {
                    path: "publication_date",
                    label: "Publication date",
                    kind: "date",
                  },
                  {
                    path: "effective_from",
                    label: "Effective from (IST)",
                    kind: "datetime",
                  },
                  {
                    path: "effective_until",
                    label: "Effective until (IST)",
                    kind: "datetime",
                  },
                  {
                    path: "retrieved_at",
                    label: "Retrieved at (IST)",
                    kind: "datetime",
                  },
                  {
                    path: "snapshot_attachment_id",
                    label: "Clean uploaded snapshot",
                    kind: attachments.length ? "select" : "text",
                    options: Object.fromEntries(
                      attachments
                        .filter(
                          (a) =>
                            a.security_state === "CLEAN" &&
                            a.purpose === "OTHER",
                        )
                        .map((a) => [a.id, a.original_name]),
                    ),
                  },
                  ...(!attachments.length
                    ? [{ path: "source_sha256", label: "Snapshot SHA-256" }]
                    : []),
                  {
                    path: "interpretation_note",
                    label: "Interpretation and limitations",
                    kind: "textarea",
                  },
                ]}
                values={source}
                onChange={setSource}
                errors={mutation.error?.fields}
              />
              <Button
                disabled={mutation.pending || !source.snapshot_attachment_id}
                onClick={() =>
                  void mutation.run("/regulations/sources", {
                    ...source,
                    jurisdictions: ["IN"],
                    source_sha256:
                      attachments.find(
                        (a) => a.id === source.snapshot_attachment_id,
                      )?.sha256 ?? source.source_sha256,
                  })
                }
              >
                <BookOpen className="size-4" />
                Register source
              </Button>
            </div>
          </details>
        )}
      </Section>
      {can("regulation.pack.prepare") && (
        <Section name="Draft typed rule pack">
          <label className="block text-sm font-medium">
            Environment
            <select
              className="mt-1 block rounded border p-2"
              value={environment}
              onChange={(e) => {
                setEnvironment(e.target.value);
                setDraft(null);
              }}
            >
              <option>PRODUCTION</option>
              <option>SIMULATION</option>
            </select>
          </label>
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium">
              Immutable source snapshots
            </legend>
            {registry.data?.sources.map((s) => (
              <label
                key={String(s.id)}
                className="flex items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  checked={sources.includes(String(s.id))}
                  onChange={() =>
                    setSources(
                      sources.includes(String(s.id))
                        ? sources.filter((i) => i !== s.id)
                        : [...sources, String(s.id)],
                    )
                  }
                />
                {String(s.title)}
              </label>
            ))}
          </fieldset>
          <Button
            variant="outline"
            disabled={!sources.length}
            onClick={async () => {
              try {
                const query = new URLSearchParams({ environment });
                sources.forEach((id) => query.append("source_ids", id));
                setDraft(
                  await tradeRequest<Values>(
                    `/regulations/candidate-template?${query.toString()}`,
                    org,
                  ),
                );
                setError("");
              } catch (e) {
                setError(
                  e instanceof Error ? e.message : "Candidate unavailable",
                );
              }
            }}
          >
            <FlaskConical className="size-4" />
            Load ordinary-road candidate
          </Button>
          {draft && (
            <>
              <details>
                <summary className="cursor-pointer font-medium">
                  Proof policies and authorisation lifetime
                </summary>
                <Fields
                  specs={[
                    {
                      path: "default_authorisation_ttl_seconds",
                      label:
                        "Authorisation maximum lifetime (seconds, up to 900)",
                      kind: "integer",
                    },
                  ]}
                  values={draft}
                  onChange={setDraft}
                />
                {Object.entries(
                  draft.proof_policy as Record<string, Values>,
                ).map(([kind, policy]) => (
                  <fieldset key={kind} className="mt-4 space-y-3">
                    <legend className="text-sm font-semibold">{kind}</legend>
                    <Fields
                      specs={[
                        {
                          path: "policy",
                          label: "Accepted proof policy",
                          kind: "select",
                          options:
                            environment === "SIMULATION"
                              ? [
                                  "SIMULATED_ONLY",
                                  "AUTHORISED_LIVE_ONLY",
                                  "AUTHORISED_LIVE_OR_REVIEWED_MANUAL",
                                ]
                              : [
                                  "AUTHORISED_LIVE_ONLY",
                                  "AUTHORISED_LIVE_OR_REVIEWED_MANUAL",
                                ],
                        },
                        {
                          path: "maximum_age_seconds",
                          label: "Maximum observation age (seconds)",
                          kind: "integer",
                        },
                        {
                          path: "supporting_evidence_required",
                          label: "Supporting evidence required",
                          kind: "boolean",
                        },
                      ]}
                      values={policy}
                      onChange={(next) =>
                        setDraft({
                          ...draft,
                          proof_policy: {
                            ...(draft.proof_policy as Values),
                            [kind]: next,
                          },
                        })
                      }
                    />
                  </fieldset>
                ))}
              </details>
              <Fields
                specs={[
                  { path: "title", label: "Pack title" },
                  { path: "version", label: "Version" },
                  {
                    path: "effective_from",
                    label: "Effective from (IST)",
                    kind: "datetime",
                  },
                  {
                    path: "effective_until",
                    label: "Effective until (IST)",
                    kind: "datetime",
                  },
                ]}
                values={draft}
                onChange={setDraft}
              />
              <details>
                <summary className="cursor-pointer font-medium">
                  Supported scope predicate
                </summary>
                <RuleExpression
                  value={draft.supported_scope_predicate as Expression}
                  onChange={(expr) =>
                    setDraft({ ...draft, supported_scope_predicate: expr })
                  }
                />
              </details>
              {(draft.rules as Values[]).map((rule, index) => (
                <details key={String(rule.rule_code)} className="border-b py-3">
                  <summary className="cursor-pointer font-medium">
                    {String(rule.rule_code)}
                  </summary>
                  <Fields
                    specs={[
                      { path: "rule_version", label: "Rule version" },
                      {
                        path: "class",
                        label: "Rule class",
                        kind: "select",
                        options: [
                          "LEGAL_REQUIREMENT",
                          "PORTAL_CONTROL",
                          "APPLICATION_POLICY",
                        ],
                      },
                      {
                        path: "date_basis",
                        label: "Date basis",
                        kind: "select",
                        options: [
                          "ACTION_TIME",
                          "INVOICE_DATE",
                          "OBSERVATION_TIME",
                          "PLANNED_ARRIVAL_TIME",
                        ],
                      },
                      {
                        path: "effective_from",
                        label: "Effective from (IST)",
                        kind: "datetime",
                      },
                      {
                        path: "effective_until",
                        label: "Effective until (IST)",
                        kind: "datetime",
                      },
                      {
                        path: "explanation_template",
                        label: "Explanation and legal / policy distinction",
                        kind: "textarea",
                      },
                    ]}
                    values={rule}
                    onChange={(next) =>
                      setDraft({
                        ...draft,
                        rules: (draft.rules as Values[]).map((r, i) =>
                          i === index ? next : r,
                        ),
                      })
                    }
                  />
                  <h4 className="mt-3 text-sm font-semibold">Applicability</h4>
                  <RuleExpression
                    value={rule.applicability_expression as Expression}
                    onChange={(expr) =>
                      setDraft({
                        ...draft,
                        rules: (draft.rules as Values[]).map((r, i) =>
                          i === index
                            ? { ...r, applicability_expression: expr }
                            : r,
                        ),
                      })
                    }
                  />
                  <h4 className="mt-3 text-sm font-semibold">Satisfaction</h4>
                  <RuleExpression
                    value={rule.satisfaction_expression as Expression}
                    onChange={(expr) =>
                      setDraft({
                        ...draft,
                        rules: (draft.rules as Values[]).map((r, i) =>
                          i === index
                            ? { ...r, satisfaction_expression: expr }
                            : r,
                        ),
                      })
                    }
                  />
                </details>
              ))}
              <Button
                disabled={mutation.pending}
                onClick={async () => {
                  const result = await mutation.run(
                    "/regulations/rule-pack-revisions",
                    draft,
                  );
                  if (result) setDraft(null);
                }}
              >
                <Save className="size-4" />
                Save immutable candidate revision
              </Button>
            </>
          )}
        </Section>
      )}
      {!!registry.data?.source_conflicts.length && (
        <Section name="Material source conflicts">
          {registry.data.source_conflicts.map((c) => (
            <article key={String(c.id)} className="space-y-3 border-b py-3">
              <Status value={String(c.status)} />
              <p className="text-sm">{String(c.issue)}</p>
              <Facts
                values={{
                  sources: c.source_ids,
                  resolution: c.resolution_json,
                }}
              />
              {can("regulation.pack.review") &&
                c.status === "OPEN" &&
                c.created_by_user_id !== me.user.id && (
                  <ConflictResolution conflict={c} reload={registry.reload} />
                )}
            </article>
          ))}
        </Section>
      )}
      {can("regulation.source.register") && (
        <Section name="Record a material source conflict">
          <Facts values={{ selected_sources: sources }} />
          <ActionForm
            name="Register selected-source conflict"
            key={sources.join(",")}
            path="/regulations/source-conflicts"
            initial={{
              source_ids: sources,
              scope: { family: "INDIA_ORDINARY_INTERSTATE_ROAD_SALE" },
            }}
            specs={[
              {
                path: "issue",
                label: "Conflicting interpretation",
                kind: "textarea",
                required: true,
              },
            ]}
            reload={registry.reload}
          />
        </Section>
      )}
      {(error || mutation.error) && (
        <p role="alert" className="text-sm text-red-800">
          {error || mutation.error?.message}
        </p>
      )}
    </div>
  );
}

function ConflictResolution({
  conflict,
  reload,
}: {
  conflict: Values;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const mutation = useOperationalMutation(org, reload);
  const [chosen, setChosen] = useState<string[]>([]);
  const [values, setValues] = useState<Values>({});
  return (
    <div className="space-y-3">
      <fieldset>
        <legend className="text-sm font-medium">Governing sources</legend>
        {(conflict.source_ids as string[]).map((id) => (
          <label key={id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={chosen.includes(id)}
              onChange={() =>
                setChosen(
                  chosen.includes(id)
                    ? chosen.filter((i) => i !== id)
                    : [...chosen, id],
                )
              }
            />
            {id}
          </label>
        ))}
      </fieldset>
      <Fields
        specs={[
          {
            path: "resolution",
            label: "Governing interpretation",
            kind: "textarea",
            required: true,
          },
          ...reason,
        ]}
        values={values}
        onChange={setValues}
      />
      <Button
        disabled={!chosen.length || mutation.pending}
        onClick={() =>
          void mutation.run(
            `/regulations/source-conflicts/${conflict.id}/resolutions`,
            { ...values, governing_source_ids: chosen },
          )
        }
      >
        <BookOpen className="size-4" />
        Resolve source conflict
      </Button>
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
    </div>
  );
}
