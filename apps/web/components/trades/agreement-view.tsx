import {
  displayMoney,
  displayTime,
  type Revision,
  type Values,
} from "@/lib/trades";

function label(value: string) {
  return value.replaceAll("_", " ");
}
function Value({ value }: { value: unknown }) {
  if (value == null || value === "")
    return <span className="text-muted">Not provided</span>;
  if (Array.isArray(value))
    return (
      <ol className="space-y-3">
        {value.map((item, index) => (
          <li key={index}>
            <Value value={item} />
          </li>
        ))}
      </ol>
    );
  if (typeof value === "object")
    return (
      <dl className="grid gap-2 sm:grid-cols-2">
        {Object.entries(value as Values)
          .filter(([key]) => !["line_ref", "line_no"].includes(key))
          .map(([key, item]) => (
            <div key={key} className="min-w-0">
              <dt className="text-xs text-muted">{label(key)}</dt>
              <dd className="break-words text-sm">
                <Value value={item} />
              </dd>
            </div>
          ))}
      </dl>
    );
  return (
    <>{typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}</>
  );
}
export function AgreementView({
  revision,
  title,
}: {
  revision: Revision;
  title: string;
}) {
  const facts = revision.facts;
  const items = (facts.items ?? []) as Values[];
  return (
    <section className="space-y-5 border-y border-line py-5" aria-label={title}>
      <div>
        <h2 className="text-xl font-semibold">{title}</h2>
        <p className="mt-1 text-sm text-secondary">
          Revision {revision.revision_number} |{" "}
          {displayTime(revision.created_at)} IST
        </p>
        <p className="mt-1 break-all font-mono text-xs text-muted">
          Terms hash: {revision.terms_hash}
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <p className="text-xs text-muted">Quoted goods value</p>
          <p className="text-lg font-semibold">
            {displayMoney(revision.pricing_summary.quoted_goods_total_minor)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Complete declared tax estimate</p>
          <p className="font-semibold">
            {displayMoney(revision.pricing_summary.complete_tax_estimate_minor)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Separate freight estimate</p>
          <p className="font-semibold">
            {displayMoney(revision.pricing_summary.freight_estimate_minor)}
          </p>
        </div>
      </div>
      <p className="text-sm text-secondary">
        {String(revision.pricing_summary.tax_note ?? "Tax not assessed")}{" "}
        {String(revision.pricing_summary.freight_note ?? "")} Unknown charges
        remain unassessed.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">
            Goods lines; all unit prices and discounts in integer or fractional
            paise
          </caption>
          <thead>
            <tr className="border-b border-line">
              <th className="py-2">Goods</th>
              <th>Quantity / unit</th>
              <th>Unit price (paise)</th>
              <th>Discount (paise)</th>
              <th>Quoted line value</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr
                key={String(item.line_ref ?? index)}
                className="border-b border-line"
              >
                <td className="min-w-40 py-3 pr-3">
                  <strong>
                    {String(item.description ?? "Incomplete goods line")}
                  </strong>
                  <p className="text-xs text-muted">
                    {String(item.specification ?? "Specification not provided")}
                  </p>
                </td>
                <td>
                  {String(item.quantity ?? "-")} {String(item.uqc ?? "")}
                </td>
                <td>{String(item.unit_price_minor ?? "-")}</td>
                <td>{String(item.discount_minor ?? "0")}</td>
                <td className="whitespace-nowrap">
                  {displayMoney(item.line_quoted_total_minor)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {Object.entries(facts)
        .filter(([key]) => key !== "items")
        .map(([key, value]) => (
          <details
            key={key}
            className="border-b border-line pb-3"
            open={["bill_from", "bill_to"].includes(key)}
          >
            <summary className="cursor-pointer text-sm font-semibold">
              {label(key)}
            </summary>
            <div className="mt-3">
              <Value value={value} />
            </div>
          </details>
        ))}
      <details>
        <summary className="cursor-pointer text-sm font-semibold">
          Goods declarations
        </summary>
        <div className="mt-3">
          <Value value={items} />
        </div>
      </details>
      <p className="text-xs text-muted">
        Declarations only; registration, HSN, place of supply and final tax are
        not verified.
      </p>
    </section>
  );
}
