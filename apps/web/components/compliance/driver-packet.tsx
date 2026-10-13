"use client";
import { useState } from "react";
import { Check, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import {
  useOperationalMutation,
  useOperationsResource,
} from "@/hooks/use-operations";
import { Facts, Mode, Section } from "@/components/operations/shared";
import { displayTime, tradeRequest } from "@/lib/trades";
import type { Readiness, Packet } from "@/lib/guarded-dispatch";

export function DriverPacket({
  readiness,
  reload,
}: {
  readiness: Readiness | null;
  reload: () => Promise<void>;
}) {
  const { org } = useTradeContext();
  const packetId = readiness?.evaluation?.packets[0]?.id;
  const resource = useOperationsResource<Packet>(
    `/dispatch-packets/${packetId ?? "00000000-0000-0000-0000-000000000000"}`,
    org,
  );
  const mutation = useOperationalMutation(org, async () => {
    await resource.reload();
    await reload();
  });
  const [possession, setPossession] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const packet = packetId ? resource.data : null;
  return (
    <Section name="Prepared carried-document packet">
      {!packet && (
        <p className="text-sm text-amber-900">
          Prepared packet and independent release review required
        </p>
      )}
      {packet && (
        <>
          <Mode mode={packet.execution_mode} />
          <Facts
            values={{
              packet_hash: packet.packet_hash,
              packet_state: packet.effective_state,
              valid_until: displayTime(packet.valid_until),
            }}
          />
          {packet.items.map((item) => (
            <div
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-3 border-b py-3"
            >
              <div className="text-sm font-medium">
                {item.representation_type} / {item.carry_method}
                {!!item.source_reference_json?.printed_identifiers && (
                  <Facts
                    values={Object.fromEntries(
                      Object.entries(
                        item.source_reference_json
                          .printed_identifiers as Record<string, unknown>,
                      ).filter(
                        ([, value]) =>
                          value !== null && value !== undefined && value !== "",
                      ),
                    )}
                  />
                )}
              </div>
              {!["EWB_NUMBER", "PAPER_INVOICE_REFERENCE"].includes(
                item.representation_type,
              ) && (
                <Button
                  variant="outline"
                  disabled={packet.effective_state !== "CURRENT"}
                  onClick={async () => {
                    setDownloadError("");
                    try {
                      const result = await tradeRequest<{ url: string }>(
                        `/dispatch-packets/${packet.id}/items/${item.id}/download`,
                        org,
                      );
                      const response = await fetch(result.url, {
                        headers: { "X-Organization-Id": org },
                        cache: "no-store",
                      });
                      if (!response.ok)
                        throw new Error(
                          "Packet download unavailable or access changed",
                        );
                      const url = URL.createObjectURL(await response.blob());
                      const anchor = document.createElement("a");
                      anchor.href = url;
                      anchor.download = `${packet.execution_mode}-${item.representation_type}`;
                      anchor.click();
                      URL.revokeObjectURL(url);
                    } catch (error) {
                      setDownloadError(
                        error instanceof Error
                          ? error.message
                          : "Download failed",
                      );
                    }
                  }}
                >
                  <Download className="size-4" />
                  Prepare offline copy
                </Button>
              )}
            </div>
          ))}
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              checked={possession}
              onChange={(e) => setPossession(e.target.checked)}
            />
            I have every selected carried document / number available for this
            assignment
          </label>
          <p className="text-sm text-amber-900">
            Carrying this packet does not authorise movement. Pickup and
            departure require current online platform authorisation.
          </p>
          <Button
            disabled={
              !possession ||
              packet.effective_state !== "CURRENT" ||
              mutation.pending
            }
            onClick={() =>
              void mutation.run(
                `/dispatch-packets/${packet.id}/acknowledgments`,
                {
                  packet_hash: packet.packet_hash,
                  assignment_id: packet.assignment_id,
                  possession_confirmed: true,
                  carry_methods: Array.from(
                    new Set(packet.items.map((i) => i.carry_method)),
                  ),
                },
              )
            }
          >
            <Check className="size-4" />
            Acknowledge exact packet
          </Button>
        </>
      )}
      {downloadError && <p role="alert">{downloadError}</p>}
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
    </Section>
  );
}
