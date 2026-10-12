"use client";
import Link from "next/link";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { type Values } from "@/lib/trades";
import { ErrorNotice, Status } from "./shared";

export function DocumentTrades() {
  const { org, role } = useTradeContext();
  const data = useOperationsResource<{ items: Values[] }>(
    `/trades?role=${role}`,
    org,
  );
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold">Documents</h1>
      <ErrorNotice message={data.error} />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr>
              <th className="border-b border-line p-3">Trade</th>
              <th className="border-b border-line p-3">Agreement</th>
              <th className="border-b border-line p-3">Mode</th>
            </tr>
          </thead>
          <tbody>
            {data.data?.items.map((trade) => (
              <tr key={String(trade.trade_id)} className="border-b border-line">
                <td className="p-3">
                  <Link
                    className="font-semibold text-accent underline"
                    href={`/documents/trades/${String(trade.trade_id)}`}
                  >
                    {String(trade.reference)}
                  </Link>
                </td>
                <td className="p-3">
                  <Status value={String(trade.agreement_status)} />
                </td>
                <td className="p-3">
                  <Status value={String(trade.execution_mode)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
