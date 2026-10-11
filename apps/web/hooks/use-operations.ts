"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { tradeRequest, TradeApiError } from "@/lib/trades";

export function useOperationsResource<T>(path: string, org: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const reload = useCallback(async () => {
    const current = ++generation.current;
    if (!org) return;
    try {
      const result = await tradeRequest<T>(path, org);
      if (current === generation.current) {
        setData(result);
        setError("");
      }
    } catch (problem) {
      if (current === generation.current)
        setError(
          problem instanceof Error ? problem.message : "Record unavailable",
        );
    }
  }, [path, org]);
  useEffect(() => {
    const counter = generation;
    setData(null);
    void reload();
    return () => {
      counter.current++;
    };
  }, [reload]);
  return { data, error, reload };
}

export function useOperationalMutation(
  org: string,
  reload: () => Promise<void>,
) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<TradeApiError | null>(null);
  const [saved, setSaved] = useState("");
  const requests = useRef(new Map<string, string>());
  async function run<T>(
    path: string,
    body: unknown,
    etag?: string,
    method = "POST",
  ): Promise<T | undefined> {
    const fingerprint = JSON.stringify([org, method, path, body]);
    const key = requests.current.get(fingerprint) ?? crypto.randomUUID();
    requests.current.set(fingerprint, key);
    setPending(true);
    setError(null);
    setSaved("");
    try {
      const result = await tradeRequest<T>(path, org, method, body, etag, key);
      requests.current.delete(fingerprint);
      setSaved("Recorded");
      await reload();
      return result;
    } catch (problem) {
      setError(
        problem instanceof TradeApiError
          ? problem
          : new TradeApiError(
              "REQUEST_FAILED",
              problem instanceof Error ? problem.message : "Action failed",
            ),
      );
      await reload();
    } finally {
      setPending(false);
    }
  }
  return { run, pending, error, saved };
}
