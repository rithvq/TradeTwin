"use client";
import { useState } from "react";
import Link from "next/link";
import { Archive, Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDocumentVersion } from "@/hooks/use-document-desk";
import {
  useOperationsResource,
  useOperationalMutation,
} from "@/hooks/use-operations";
import { type Operations } from "@/lib/operations";
import { type Trade, type Values } from "@/lib/trades";
import { InputLabel } from "./register";
import { ErrorNotice } from "./shared";

export function DocumentMaintenance({
  desk,
}: {
  desk: ReturnType<typeof useDocumentVersion>;
}) {
  const { doc, version, org } = desk;
  const ops = useOperationsResource<Operations>(
    `/trades/${doc?.trade_id ?? "00000000-0000-0000-0000-000000000000"}/operations`,
    org,
  );
  const trade = useOperationsResource<Trade>(
    `/trades/${doc?.trade_id ?? "00000000-0000-0000-0000-000000000000"}`,
    org,
  );
  const facts =
    trade.data?.accepted_revision?.facts ??
    trade.data?.current_candidate_revision?.facts;
  const [file, setFile] = useState("");
  const [reason, setReason] = useState("");
  const [versionReason, setVersionReason] = useState("CLEARER_COPY");
  const [grantee, setGrantee] = useState("");
  const [shareType, setShareType] = useState("READ_REVIEWED");
  const [subjectType, setSubjectType] = useState("CONSIGNMENT");
  const [subject, setSubject] = useState("");
  const [relationship, setRelationship] = useState("DUPLICATE_PRESENTATION_OF");
  const [target, setTarget] = useState("");
  const [assignment, setAssignment] = useState("");
  const history = useOperationsResource<{
    access_history?: Values[];
    subject_link_history?: Values[];
  }>(
    `/document-versions/${version?.id ?? "00000000-0000-0000-0000-000000000000"}/evidence-manifest`,
    org,
  );
  const register = useOperationsResource<{
    items: { id: string; label: string }[];
  }>(
    `/trades/${doc?.trade_id ?? "00000000-0000-0000-0000-000000000000"}/documents`,
    org,
  );
  const mutation = useOperationalMutation(org, async () => {
    await desk.reload();
    await history.reload();
  });
  if (!doc || !version) return null;
  return (
    <div className="space-y-4">
      <ErrorNotice message={mutation.error?.message ?? ""} />
      <details>
        <summary className="cursor-pointer text-sm font-semibold">
          Source versions and original hashes
        </summary>
        <div className="mt-3 space-y-2">
          {doc.versions.map((v) => (
            <p key={v.id} className="break-all text-xs">
              <Link
                className="font-medium text-accent underline"
                href={`/documents/versions/${v.id}/review`}
              >
                Source v{v.version_number}
              </Link>{" "}
              / {v.reason} / {v.source_manifest_hash}
            </p>
          ))}
        </div>
      </details>
      {doc.allowed_actions.includes("document.version.add") && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            Register a new source copy
          </summary>
          <form
            className="mt-3 grid gap-3 sm:grid-cols-2"
            onSubmit={async (e) => {
              e.preventDefault();
              await mutation.run(
                `/documents/${doc.id}/versions`,
                {
                  reason: versionReason,
                  reason_text: reason,
                  primary_attachment_id: file,
                  supporting_assets: [],
                },
                doc.etag,
              );
            }}
          >
            <InputLabel text="New clean attachment">
              <select
                required
                value={file}
                onChange={(e) => setFile(e.target.value)}
              >
                <option value="">Select clean file</option>
                {ops.data?.documents
                  .filter((a) => a.security_state === "CLEAN")
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.original_name}
                    </option>
                  ))}
              </select>
            </InputLabel>
            <InputLabel text="Source-copy reason">
              <select
                value={versionReason}
                onChange={(e) => setVersionReason(e.target.value)}
              >
                {[
                  "CLEARER_COPY",
                  "ADDITIONAL_PAGES",
                  "UPDATED_RECORD_COPY",
                  "OTHER",
                ].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </InputLabel>
            <InputLabel text="Reason details">
              <input
                required
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </InputLabel>
            <Button variant="outline" disabled={mutation.pending}>
              Add source version
            </Button>
          </form>
        </details>
      )}
      {doc.allowed_actions.includes("document.share") && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            Share reviewed evidence
          </summary>
          <form
            className="mt-3 grid gap-3 sm:grid-cols-2"
            onSubmit={async (e) => {
              e.preventDefault();
              await mutation.run(
                `/document-versions/${version.id}/access-grants`,
                {
                  grantee_organization_id:
                    shareType === "OPERATIONAL_PROJECTION"
                      ? ops.data?.consignments
                          .flatMap((c) => c.assignments)
                          .find((a) => a.id === assignment)
                          ?.carrier_organization_id
                      : grantee,
                  access_type: shareType,
                  assignment_id:
                    shareType === "OPERATIONAL_PROJECTION" ? assignment : null,
                  allowed_field_paths:
                    shareType === "OPERATIONAL_PROJECTION"
                      ? [
                          "header.document_number",
                          "packing_transport.lr_gr_number",
                          "packing_transport.package_count",
                          "packing_transport.gross_weight_kg",
                          "packing_transport.vehicle_registration_number",
                        ]
                      : [],
                },
              );
            }}
          >
            <InputLabel text="Trade-party organisation">
              <select
                required={shareType !== "OPERATIONAL_PROJECTION"}
                value={grantee}
                onChange={(e) => setGrantee(e.target.value)}
              >
                <option value="">Select trade party</option>
                {["seller_organization_id", "buyer_organization_id"].map(
                  (key) =>
                    facts?.[key] ? (
                      <option key={key} value={String(facts[key])}>
                        {key.startsWith("seller") ? "Seller" : "Buyer"}
                      </option>
                    ) : null,
                )}
              </select>
            </InputLabel>
            <InputLabel text="Access level">
              <select
                value={shareType}
                onChange={(e) => setShareType(e.target.value)}
              >
                <option value="READ_REVIEWED">Reviewed values only</option>
                <option value="DOWNLOAD_ORIGINAL">
                  Source / original access
                </option>
                {[
                  "LR_GR",
                  "POD",
                  "PACKING_LIST",
                  "EWAY_BILL_COPY",
                  "DELIVERY_CHALLAN",
                ].includes(doc.document_type) && (
                  <option value="OPERATIONAL_PROJECTION">
                    Active carrier operational fields only
                  </option>
                )}
              </select>
            </InputLabel>
            {shareType === "OPERATIONAL_PROJECTION" && (
              <InputLabel text="Active accepted assignment">
                <select
                  value={assignment}
                  required
                  onChange={(e) => setAssignment(e.target.value)}
                >
                  <option value="">Select assignment</option>
                  {ops.data?.consignments.flatMap((c) =>
                    c.assignments
                      .filter((a) => a.id === c.active_assignment_id)
                      .map((a) => (
                        <option key={a.id} value={a.id}>
                          {c.reference} / {a.id.slice(0, 8)}
                        </option>
                      )),
                  )}
                </select>
              </InputLabel>
            )}
            <Button variant="outline" disabled={mutation.pending}>
              <Share2 className="size-4" />
              Share evidence
            </Button>
          </form>
          {history.data?.access_history?.map((grant) => (
            <div
              key={String(grant.id)}
              className="mt-3 flex flex-wrap items-center gap-3 text-sm"
            >
              <span>
                {String(grant.access_type)} /{" "}
                {grant.revoked_at ? "Revoked" : "Active"}
              </span>
              {!grant.revoked_at && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={mutation.pending}
                  onClick={() =>
                    void mutation.run(
                      `/document-access-grants/${String(grant.id)}/revocations`,
                      { reason: "Owner revoked evidence sharing" },
                    )
                  }
                >
                  Revoke access
                </Button>
              )}
            </div>
          ))}
        </details>
      )}
      {doc.allowed_actions.includes("document.register") && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            Link an operational record
          </summary>
          <form
            className="mt-3 grid gap-3 sm:grid-cols-2"
            onSubmit={async (e) => {
              e.preventDefault();
              await mutation.run(
                `/document-versions/${version.id}/subject-links`,
                { subject_type: subjectType, subject_id: subject },
              );
            }}
          >
            <InputLabel text="Subject type">
              <select
                value={subjectType}
                onChange={(e) => setSubjectType(e.target.value)}
              >
                {["CONSIGNMENT", "RECEIPT", "PAYMENT", "DISPUTE"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </InputLabel>
            <InputLabel text="Subject ID">
              <input
                required
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                list="document-subjects"
              />
            </InputLabel>
            <datalist id="document-subjects">
              {ops.data?.consignments.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.reference}
                </option>
              ))}
            </datalist>
            <Button variant="outline" disabled={mutation.pending}>
              Link record
            </Button>
          </form>
        </details>
      )}
      {doc.allowed_actions.includes("document.review.submit") && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            Document relationships / duplicate presentation
          </summary>
          <form
            className="mt-3 grid gap-3 sm:grid-cols-2"
            onSubmit={async (e) => {
              e.preventDefault();
              await mutation.run(
                `/documents/${doc.id}/relationships`,
                {
                  to_document_id: target,
                  relationship_type: relationship,
                  reason,
                },
                doc.etag,
              );
            }}
          >
            <InputLabel text="Related document">
              <select
                required
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="">Select accessible document</option>
                {register.data?.items
                  .filter((d) => d.id !== doc.id)
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.label}
                    </option>
                  ))}
              </select>
            </InputLabel>
            <InputLabel text="Relationship">
              <select
                value={relationship}
                onChange={(e) => setRelationship(e.target.value)}
              >
                {[
                  "DUPLICATE_PRESENTATION_OF",
                  "SUPERSEDES_BUSINESS_DOCUMENT",
                  "SUPPORTS",
                ].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </InputLabel>
            <InputLabel text="Relationship reason">
              <input
                required
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </InputLabel>
            <Button variant="outline" disabled={mutation.pending}>
              Record relationship
            </Button>
          </form>
        </details>
      )}
      {doc.allowed_actions.includes("document.archive") && (
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            Administrative archive
          </summary>
          <form
            className="mt-3 flex flex-wrap gap-3"
            onSubmit={async (e) => {
              e.preventDefault();
              await mutation.run(
                `/documents/${doc.id}/archives`,
                { reason },
                doc.etag,
              );
            }}
          >
            <input
              aria-label="Archive reason"
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="rounded border border-line p-2 text-sm"
            />
            <Button variant="outline" disabled={mutation.pending}>
              <Archive className="size-4" />
              Archive document
            </Button>
          </form>
        </details>
      )}
    </div>
  );
}
