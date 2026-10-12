"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTradeContext } from "@/components/trades/trade-context";
import { useOperationsResource } from "@/hooks/use-operations";
import { tradeRequest } from "@/lib/trades";
import { type Locator } from "@/lib/document-desk";
import { ErrorNotice } from "./shared";

type Page = {
  id: string;
  page_number: number;
  width_px: number;
  height_px: number;
  source_attachment_id: string;
};
export function SafePreview({
  versionId,
  source,
}: {
  versionId: string;
  source: Locator | null;
}) {
  const { org } = useTradeContext();
  const pages = useOperationsResource<{ items: Page[] }>(
    `/document-versions/${versionId}/pages`,
    org,
  );
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [sourceId, setSourceId] = useState("");
  useEffect(() => {
    if (source?.page_number) {
      setPage(source.page_number);
      setSourceId(source.source_attachment_id);
    }
  }, [source]);
  const sources = [
    ...new Set(pages.data?.items.map((p) => p.source_attachment_id) ?? []),
  ];
  const chosenSource = sourceId || sources[0];
  const latest = new Map<number, Page>();
  for (const p of pages.data?.items ?? [])
    if (p.source_attachment_id === chosenSource) latest.set(p.page_number, p);
  const record = latest.get(page);
  useEffect(() => {
    let active = true;
    let object = "";
    setUrl("");
    if (!record) return;
    void (async () => {
      try {
        const auth = await tradeRequest<{ url: string }>(
          `/document-pages/${record.id}/preview`,
          org,
        );
        const response = await fetch(auth.url, {
          headers: { "X-Organization-Id": org },
          cache: "no-store",
        });
        if (!response.ok)
          throw new Error("Preview access expired or is unavailable");
        object = URL.createObjectURL(await response.blob());
        if (active) {
          setUrl(object);
          setError("");
        } else URL.revokeObjectURL(object);
      } catch (problem) {
        if (active)
          setError(
            problem instanceof Error ? problem.message : "Preview unavailable",
          );
      }
    })();
    return () => {
      active = false;
      if (object) URL.revokeObjectURL(object);
    };
  }, [record, org]);
  const box =
    source?.page_number === page && source.source_attachment_id === chosenSource
      ? source.bounding_box
      : null;
  return (
    <section className="min-w-0 space-y-3">
      {sources.length > 1 && (
        <label className="text-sm">
          Source file{" "}
          <select
            aria-label="Preview source file"
            className="ml-2 max-w-full rounded border border-line p-2"
            value={chosenSource}
            onChange={(e) => {
              setSourceId(e.target.value);
              setPage(1);
            }}
          >
            {sources.map((s, i) => (
              <option key={s} value={s}>
                Source {i + 1} / {s.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button
            size="icon"
            variant="outline"
            aria-label="Previous page"
            title="Previous page"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="text-xs tabular-nums">
            Page {page} / {latest.size}
          </span>
          <Button
            size="icon"
            variant="outline"
            aria-label="Next page"
            title="Next page"
            disabled={page >= latest.size}
            onClick={() => setPage(page + 1)}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
        <div className="flex gap-1">
          <Button
            size="icon"
            variant="outline"
            aria-label="Zoom out"
            title="Zoom out"
            disabled={zoom <= 0.5}
            onClick={() => setZoom(zoom - 0.25)}
          >
            <Minus className="size-4" />
          </Button>
          <Button
            size="icon"
            variant="outline"
            aria-label="Zoom in"
            title="Zoom in"
            disabled={zoom >= 2.5}
            onClick={() => setZoom(zoom + 0.25)}
          >
            <Plus className="size-4" />
          </Button>
        </div>
      </div>
      <ErrorNotice message={pages.error || error} />
      <div className="max-h-[70svh] min-h-64 overflow-auto border border-line bg-surface-raised p-2">
        {record ? (
          <div
            className="relative bg-white"
            style={{
              width: `${zoom * 100}%`,
              aspectRatio: `${record.width_px}/${record.height_px}`,
            }}
          >
            {url ? (
              <Image
                src={url}
                unoptimized
                width={record.width_px}
                height={record.height_px}
                alt={`Safe rendering, source page ${page}`}
                className="h-full w-full"
              />
            ) : (
              <p className="p-5 text-sm text-secondary">
                Loading safe rendering...
              </p>
            )}
            {box && (
              <div
                aria-label="Selected field source location"
                className="pointer-events-none absolute border-2 border-accent bg-teal-300/20"
                style={{
                  left: `${box.x0 * 100}%`,
                  top: `${box.y0 * 100}%`,
                  width: `${(box.x1 - box.x0) * 100}%`,
                  height: `${(box.y1 - box.y0) * 100}%`,
                }}
              />
            )}
          </div>
        ) : (
          <p className="p-5 text-sm text-secondary">
            {source?.json_pointer
              ? `Structured JSON source: ${source.json_pointer}`
              : "No rendered page is available for this source."}
          </p>
        )}
      </div>
    </section>
  );
}
