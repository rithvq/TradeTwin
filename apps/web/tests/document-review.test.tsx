import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewDesk } from "@/components/document-desk/review";
import type { useDocumentVersion } from "@/hooks/use-document-desk";
import type {
  DocumentRecord,
  FactRevision,
  Observation,
} from "@/lib/document-desk";
import { tradeRequest } from "@/lib/trades";

vi.mock("@/components/document-desk/preview", () => ({
  SafePreview: () => <div>Source preview</div>,
}));
vi.mock("@/lib/trades", async (original) => ({
  ...(await original<typeof import("@/lib/trades")>()),
  tradeRequest: vi.fn(),
}));

function reviewFixture(): ReturnType<typeof useDocumentVersion> {
  const canonical = {
    header: { document_number: "INV-000001" },
    parties: { supplier: { gstin: "33ABCDEI234F1Z5" } },
    lines: [{ document_line_ref: "line-one", quantity: "100", uqc: "NOS" }],
  };
  const observations: Observation[] = [
    ["header.document_number", null, "INV-000001"],
    ["parties.supplier.gstin", null, "33ABCDEI234F1Z5"],
    ["lines.*.quantity", "row-one", "100"],
    ["lines.*.uqc", "row-one", "NOS"],
  ].map(([path, row, value], index) => ({
    id: `observation-${index}`,
    field_path: path!,
    row_key: row,
    raw_text: value,
    normalised_value_json: value,
    extraction_method: "SIMULATION_FIXTURE",
    provider_confidence: "0.58",
    validation_status: "PARSED",
    source_locator_json: { source_attachment_id: "source-one", page_number: 1 },
    normalisation_warnings_json: [],
  }));
  return {
    org: "seller",
    doc: {
      id: "document-one",
      current_version_id: "version-one",
      latest_draft_fact_revision_id: "fact-one",
      etag: '"document-1"',
      allowed_actions: ["document.review", "document.review.submit"],
    } as DocumentRecord,
    version: {
      id: "version-one",
      document_id: "document-one",
      version_number: 1,
      source_manifest_hash: "source-hash",
      reason: "Upload",
      assets: [],
    },
    fact: {
      id: "fact-one",
      document_id: "document-one",
      document_version_id: "version-one",
      extraction_run_id: "run-one",
      revision_number: 1,
      canonical_document_json: canonical,
      content_hash: "fact-hash",
      etag: '"fact-1"',
      field_decisions: [],
    } satisfies FactRevision,
    observations,
    observationsReady: true,
    runs: [],
    candidate: null,
    selectExtraction: vi.fn(),
    job: null,
    watchJob: vi.fn(),
    reload: vi.fn().mockResolvedValue(undefined),
    error: "",
  };
}

function confirmAndCorrect() {
  fireEvent.click(
    screen.getByRole("button", { name: "Confirm proposed values" }),
  );
  fireEvent.change(screen.getByLabelText("Value parties.supplier.gstin"), {
    target: { value: "33ABCDE1234F1Z5" },
  });
  fireEvent.change(screen.getByLabelText("Reason parties.supplier.gstin"), {
    target: { value: "Corrected I to 1 against the source." },
  });
}

beforeEach(() => {
  vi.mocked(tradeRequest).mockReset();
  vi.mocked(tradeRequest).mockResolvedValue({ fields: [] });
});

describe("Document review refreshes", () => {
  it("keeps line observations during Strict Mode's repeated initialization", () => {
    render(
      <StrictMode>
        <ReviewDesk desk={reviewFixture()} />
      </StrictMode>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm proposed values" }),
    );
    expect(
      screen.getByLabelText("Decision lines.line-one.quantity"),
    ).toHaveValue("CONFIRMED");
    expect(screen.getByLabelText("Decision lines.line-one.uqc")).toHaveValue(
      "CONFIRMED",
    );
  });

  it("preserves confirmed values and corrections when job polling reloads the same source", async () => {
    const desk = reviewFixture();
    const { rerender } = render(<ReviewDesk desk={desk} />);
    confirmAndCorrect();
    rerender(
      <ReviewDesk
        desk={{
          ...desk,
          fact: structuredClone(desk.fact),
          observations: structuredClone(desk.observations),
        }}
      />,
    );
    expect(screen.getByLabelText("Value parties.supplier.gstin")).toHaveValue(
      "33ABCDE1234F1Z5",
    );
    expect(screen.getByLabelText("Reason parties.supplier.gstin")).toHaveValue(
      "Corrected I to 1 against the source.",
    );
    expect(
      screen.getByLabelText("Decision header.document_number"),
    ).toHaveValue("CONFIRMED");
    fireEvent.click(screen.getByRole("button", { name: "Save review draft" }));
    await waitFor(() =>
      expect(tradeRequest).toHaveBeenCalledWith(
        "/document-versions/version-one/fact-revisions",
        "seller",
        "POST",
        expect.objectContaining({
          base_fact_revision_id: "fact-one",
          extraction_run_id: "run-one",
          field_decisions: expect.arrayContaining([
            expect.objectContaining({
              field_path: "parties.supplier.gstin",
              decision: "CORRECTED",
              observation_id: "observation-1",
              effective_value: "33ABCDE1234F1Z5",
            }),
          ]),
          line_alignments: [
            { candidate_row_key: "row-one", document_line_ref: "line-one" },
          ],
        }),
        '"document-1"',
        expect.any(String),
      ),
    );
  });

  it("attaches late source observations without overwriting edits", () => {
    const desk = reviewFixture();
    const { rerender } = render(
      <ReviewDesk desk={{ ...desk, observations: [] }} />,
    );
    fireEvent.change(screen.getByLabelText("Value parties.supplier.gstin"), {
      target: { value: "33ABCDE1234F1Z5" },
    });
    fireEvent.change(screen.getByLabelText("Reason parties.supplier.gstin"), {
      target: { value: "Read from source" },
    });
    rerender(<ReviewDesk desk={desk} />);
    expect(screen.getByLabelText("Value parties.supplier.gstin")).toHaveValue(
      "33ABCDE1234F1Z5",
    );
    expect(screen.getByLabelText("Reason parties.supplier.gstin")).toHaveValue(
      "Read from source",
    );
    expect(
      screen.getByLabelText("Decision parties.supplier.gstin"),
    ).toHaveValue("CORRECTED");
    expect(screen.getByText("Source: 33ABCDEI234F1Z5")).toBeVisible();
  });

  it("does not replace a correction with bulk confirmation", () => {
    render(<ReviewDesk desk={reviewFixture()} />);
    confirmAndCorrect();
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm proposed values" }),
    );
    expect(
      screen.getByLabelText("Decision parties.supplier.gstin"),
    ).toHaveValue("CORRECTED");
  });

  it("initializes a different snapshot rather than carrying decisions into it", () => {
    const desk = reviewFixture();
    const { rerender } = render(<ReviewDesk desk={desk} />);
    confirmAndCorrect();
    rerender(
      <ReviewDesk
        desk={{
          ...desk,
          fact: {
            ...desk.fact!,
            id: "fact-two",
            canonical_document_json: {
              ...desk.fact!.canonical_document_json,
              header: { document_number: "INV-000002" },
            },
          },
        }}
      />,
    );
    expect(screen.getByLabelText("Value header.document_number")).toHaveValue(
      "INV-000002",
    );
    expect(
      screen.getByLabelText("Decision header.document_number"),
    ).toHaveValue("");
    expect(screen.getByLabelText("Reason parties.supplier.gstin")).toHaveValue(
      "",
    );
  });

  it("still requires a review decision for every captured field", () => {
    render(<ReviewDesk desk={reviewFixture()} />);
    fireEvent.click(screen.getByRole("button", { name: "Save review draft" }));
    expect(
      screen.getByText("Choose a review decision for every captured value."),
    ).toBeVisible();
    expect(
      vi
        .mocked(tradeRequest)
        .mock.calls.some(([path]) => path.endsWith("/fact-revisions")),
    ).toBe(false);
  });

  it("waits for the selected extraction source before allowing a save", () => {
    const desk = reviewFixture();
    const { rerender } = render(
      <ReviewDesk
        desk={{ ...desk, observations: [], observationsReady: false }}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Save review draft" }),
    ).toBeDisabled();
    rerender(<ReviewDesk desk={desk} />);
    expect(
      screen.getByRole("button", { name: "Save review draft" }),
    ).toBeEnabled();
  });

  it("does not carry saved confirmations into a different extraction candidate", () => {
    const desk = reviewFixture();
    desk.fact!.field_decisions = [
      {
        field_path: "header.document_number",
        observation_id: "observation-0",
        decision: "CONFIRMED",
        effective_value_json: "INV-000001",
        provenance: "EXTRACTION_REVIEW",
        reason: null,
        source_locator_json: null,
      },
    ];
    const { rerender } = render(<ReviewDesk desk={desk} />);
    expect(
      screen.getByLabelText("Decision header.document_number"),
    ).toHaveValue("CONFIRMED");
    rerender(
      <ReviewDesk
        desk={{
          ...desk,
          candidate: {
            id: "run-two",
            engine_kind: "NATIVE_TEXT",
            engine_name: "Parser",
            created_at: "2026-10-12T00:00:00Z",
            proposed_document_json: desk.fact!.canonical_document_json,
          },
          observations: [],
          observationsReady: false,
        }}
      />,
    );
    expect(
      screen.getByLabelText("Decision header.document_number"),
    ).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Save review draft" }),
    ).toBeDisabled();
  });
});
