import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Dimensions, Status } from "@/components/document-desk/shared";
import {
  flattenDocument,
  setDocumentField,
  printable,
} from "@/lib/document-desk";

describe("Document evidence boundaries", () => {
  it("preserves decimal and money strings under immutable corrections", () => {
    const source = {
      header: { document_number: "0000123" },
      lines: [
        {
          document_line_ref: "stable-line",
          quantity: "100.000001",
          unit_price_minor: "10000.000000",
        },
      ],
      totals: { grand_total_minor: "1180000" },
    };
    const changed = setDocumentField(
      source,
      "lines.stable-line.quantity",
      "99.000001",
    );
    expect(flattenDocument(source)["lines.stable-line.quantity"]).toBe(
      "100.000001",
    );
    expect(flattenDocument(changed)["lines.stable-line.quantity"]).toBe(
      "99.000001",
    );
    expect(flattenDocument(changed)["totals.grand_total_minor"]).toBe(
      "1180000",
    );
    expect(flattenDocument(changed)["header.document_number"]).toBe("0000123");
  });
  it("does not invent values for null fields or confidence", () => {
    expect(flattenDocument({ header: { irn: null }, lines: [] })).toEqual({});
    expect(printable(null)).toBe("Missing");
    render(<Status value="KEY_UNAVAILABLE" />);
    expect(screen.getByText("Key unavailable")).toBeVisible();
  });
  it("keeps signature validity independent of live authority and dispatch", () => {
    render(
      <Dimensions
        document={{
          status_dimensions: {
            signature_integrity: "VALID",
            authority_lookup: "NOT_CONFIGURED",
            dispatch_readiness: "NOT_ASSESSED",
            human_review: "REVIEWED",
          },
        }}
      />,
    );
    expect(screen.getByText("Valid")).toBeVisible();
    expect(screen.getByText("Not configured")).toBeVisible();
    expect(screen.getByText("Not assessed")).toBeVisible();
    expect(
      screen.queryByText("Verified", { exact: true }),
    ).not.toBeInTheDocument();
  });
});
