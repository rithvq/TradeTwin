"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { DISPATCH_CHANGED, DISPATCH_STORAGE } from "@/lib/dispatch-dashboard";
import { tradeRequest, type Me } from "@/lib/trades";

export function useDispatchOrganization() {
  const [me, setMe] = useState<Me | null>(null);
  const [selected, select] = useState("");
  const [error, setError] = useState(false);
  useEffect(() => {
    let generation = 0,
      active = true;
    async function load() {
      const current = ++generation;
      try {
        const profile = await tradeRequest<Me>("/me");
        if (!active || generation !== current) return;
        setMe(profile);
        setError(false);
        try {
          select(localStorage.getItem("tt-commercial-org") ?? "");
        } catch {
          select("");
        }
      } catch {
        if (active && current === generation) {
          setError(true);
          setMe(null);
        }
      }
    }
    void load();
    window.addEventListener("focus", load);
    window.addEventListener(DISPATCH_CHANGED, load);
    return () => {
      active = false;
      window.removeEventListener("focus", load);
      window.removeEventListener(DISPATCH_CHANGED, load);
    };
  }, []);
  const org = me?.memberships.some((m) => m.organization_id === selected)
    ? selected
    : (me?.memberships.find(
        (m) => !m.capabilities?.includes("SELLER_DEMO_EXPLORER"),
      )?.organization_id ?? "");
  function setOrg(value: string) {
    select(value);
    try {
      localStorage.setItem("tt-commercial-org", value);
    } catch {
      /* Optional preference. */
    }
  }
  return { me, org, setOrg, error };
}

export function useLiveDispatch<T>(
  path: string,
  org: string,
  interval: number,
) {
  const key = org + ":" + path;
  const generation = useRef(0);
  const inFlight = useRef<AbortController | null>(null);
  const [state, setState] = useState<{
    key: string;
    data: T | null;
    error: boolean;
    loading: boolean;
  }>({ key: "", data: null, error: false, loading: false });
  const refresh = useCallback(
    async (force = false) => {
      if (inFlight.current && !force) return;
      inFlight.current?.abort();
      const current = ++generation.current;
      if (!org || !path) return;
      const controller = new AbortController();
      inFlight.current = controller;
      const timeout = window.setTimeout(() => controller.abort(), 20_000);
      setState((previous) => ({
        key,
        data: previous.key === key ? previous.data : null,
        error: false,
        loading: true,
      }));
      try {
        const data = await tradeRequest<T>(
          path,
          org,
          "GET",
          undefined,
          undefined,
          undefined,
          controller.signal,
        );
        if (generation.current === current)
          setState({ key, data, error: false, loading: false });
      } catch {
        if (generation.current === current)
          setState({ key, data: null, error: true, loading: false });
      } finally {
        window.clearTimeout(timeout);
        if (inFlight.current === controller) inFlight.current = null;
      }
    },
    [key, path, org],
  );
  useEffect(() => {
    const counter = generation;
    const activeRequest = inFlight;
    void refresh();
    if (!org || !path) return;
    const timer = window.setInterval(() => void refresh(), interval);
    const changed = () => void refresh(true);
    const storage = (event: StorageEvent) => {
      if (event.key === DISPATCH_STORAGE) changed();
    };
    window.addEventListener(DISPATCH_CHANGED, changed);
    window.addEventListener("storage", storage);
    window.addEventListener("focus", changed);
    return () => {
      counter.current++;
      activeRequest.current?.abort();
      activeRequest.current = null;
      window.clearInterval(timer);
      window.removeEventListener(DISPATCH_CHANGED, changed);
      window.removeEventListener("storage", storage);
      window.removeEventListener("focus", changed);
    };
  }, [refresh, interval, org, path]);
  const invalidate = useCallback(() => {
    setState({ key, data: null, error: false, loading: true });
    void refresh(true);
  }, [key, refresh]);
  return {
    data: state.key === key ? state.data : null,
    error: state.key === key && state.error,
    loading: state.loading,
    refresh,
    invalidate,
  };
}

export function useDispatchExpiry(
  expiresAt: string | null,
  checkedAt: string | undefined,
  invalidate: () => void,
) {
  useEffect(() => {
    if (!expiresAt || !checkedAt) return;
    const remaining = Date.parse(expiresAt) - Date.parse(checkedAt);
    if (remaining <= 0) return;
    // Expiry triggers a server refresh, never a client-side grant of permission.
    const timer = window.setTimeout(
      invalidate,
      Math.min(remaining > 1000 ? remaining - 1000 : remaining, 2_147_483_647),
    );
    return () => window.clearTimeout(timer);
  }, [expiresAt, checkedAt, invalidate]);
}
