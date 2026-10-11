"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, type Shipment } from "@/lib/shipments";
import {
  stateRelationRequest,
  type Place,
  type Memory,
} from "@/lib/state-relations";

export function useRouteMemory(shipmentId: string) {
  const [shipment, setShipment] = useState<Shipment | null>(null);
  const [memory, setMemory] = useState<Memory | null>(null);
  const [places, setPlaces] = useState<Place[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [timeValue, setTimeValue] = useState(0);
  const [useHistory, setUseHistory] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selected, setSelected] = useState("");
  const [form, setForm] = useState({
    carrier: "",
    reference: "",
    total_price_inr: "",
    duration_hours: "",
    source_url: "",
    source_reference: "",
    review_note: "",
    valid_until: "",
    observed_at: "",
    coverage_confirmed: false,
  });
  const [vehicle, setVehicle] = useState({
    weight: "",
    height: "",
    width: "",
    length: "",
    axleload: "",
    hazmat: false,
  });
  const request = useCallback(
    <T>(path: string, body?: unknown) =>
      stateRelationRequest<T>(shipmentId, path, body),
    [shipmentId],
  );
  const refresh = useCallback(
    async () => setMemory(await request<Memory>("")),
    [request],
  );
  useEffect(() => {
    if (!autoRefresh || busy) return;
    const timer = setInterval(() => {
      void (async () => {
        setBusy(true);
        try {
          await request("/observe", {});
          if (memory?.records.some((r) => r.kind === "OFFER"))
            await request("/evaluate", {
              value_of_time_inr_per_hour: timeValue,
              use_observed_history: useHistory,
            });
          await refresh();
        } catch (e) {
          setMessage(
            e instanceof Error ? e.message : "Automatic refresh failed",
          );
        } finally {
          setBusy(false);
        }
      })();
    }, 60000);
    return () => clearInterval(timer);
  }, [autoRefresh, busy, memory, refresh, request, timeValue, useHistory]);
  useEffect(() => {
    void apiFetch<Shipment>(`/shipments/${shipmentId}`)
      .then((s) => {
        setShipment(s);
        if (s.domestic)
          setPlaces([
            s.domestic.origin,
            ...[...s.route_legs]
              .sort((a, b) => a.sequence_number - b.sequence_number)
              .map((l) => l.domestic!.destination),
          ]);
      })
      .catch((e) => setMessage(String(e)));
    void refresh().catch((e) => setMessage(String(e)));
  }, [shipmentId, refresh]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await action();
      await refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  const decisions = memory?.records.filter((r) => r.kind === "DECISION") ?? [];
  const decision = decisions.find((r) => r.id === selected) ?? decisions[0];
  const offers = memory?.records.filter((r) => r.kind === "OFFER") ?? [];
  function placeValue(index: number, key: keyof Place, value: string) {
    setPlaces((old) =>
      old.map((p, i) =>
        i === index
          ? {
              ...p,
              [key]: ["latitude", "longitude"].includes(key)
                ? value === ""
                  ? undefined
                  : Number(value)
                : value,
            }
          : p,
      ),
    );
  }
  return {
    shipment,
    memory,
    places,
    setPlaces,
    busy,
    message,
    setMessage,
    timeValue,
    setTimeValue,
    useHistory,
    setUseHistory,
    autoRefresh,
    setAutoRefresh,
    setSelected,
    form,
    setForm,
    vehicle,
    setVehicle,
    request,
    run,
    decisions,
    decision,
    offers,
    placeValue,
  };
}

export type RouteMemoryState = ReturnType<typeof useRouteMemory>;
