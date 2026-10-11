"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  editableFacts,
  getValue,
  setValue,
  tradeRequest,
  TradeApiError,
  type FieldError,
  type Organization,
  type Partner,
  type Trade,
  type Values,
} from "@/lib/trades";
import { defaults, address } from "@/lib/trade-draft";

export function useCommercialDraft(
  tradeId: string | undefined,
  org: string,
  interfaceRole: "SELLER" | "BUYER",
) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [trade, setTrade] = useState<Trade | null>(null);
  const role =
    tradeId && trade?.current_candidate_revision
      ? trade.current_candidate_revision.facts.seller_organization_id === org
        ? "SELLER"
        : "BUYER"
      : interfaceRole;
  const tradeRef = useRef<Trade | null>(null);
  const [facts, setFacts] = useState<Values>(defaults);
  const factsRef = useRef(facts);
  const saved = useRef("");
  const failedSnapshot = useRef("");
  const busy = useRef(false);
  const [tick, setTick] = useState(0);
  const [pending, setPending] = useState(false);
  const [saveState, setSaveState] = useState("Unsaved draft");
  const [error, setError] = useState("");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [conflict, setConflict] = useState(false);
  const [profile, setProfile] = useState<Organization | null>(null);
  const [partners, setPartners] = useState<Partner[]>([]);
  const [query, setQuery] = useState("");
  function apply(view: Trade) {
    tradeRef.current = view;
    setTrade(view);
  }
  function change(value: Values) {
    for (const [side, key] of [
      ["seller", "bill_from"],
      ["buyer", "bill_to"],
    ]) {
      if (value[`${side}_organization_id`]) {
        value = setValue(
          value,
          `${key}.organization_id`,
          value[`${side}_organization_id`],
        );
        value = setValue(
          value,
          `${key}.registration_id`,
          value[`${side}_registration_id`] ?? null,
        );
      }
    }
    factsRef.current = value;
    setFacts(value);
    setSaveState("Unsaved changes");
  }
  useEffect(() => {
    if (!org) return;
    tradeRef.current = null;
    setTrade(null);
    setConflict(false);
    let cancelled = false;
    void tradeRequest<Organization>(`/organizations/${org}`, org)
      .then((value) => {
        if (!cancelled) setProfile(value);
      })
      .catch((problem) => {
        if (!cancelled) setError(problem.message);
      });
    if (tradeId)
      void tradeRequest<Trade>(`/trades/${tradeId}`, org)
        .then((value) => {
          if (cancelled) return;
          apply(value);
          const next = editableFacts(
            value.current_candidate_revision?.facts ?? {},
          );
          saved.current = JSON.stringify(next);
          factsRef.current = next;
          setFacts(next);
          setSaveState("Saved");
        })
        .catch((problem) => {
          if (!cancelled) setError(problem.message);
        });
    else {
      const next = setValue(
        defaults(),
        `${role.toLowerCase()}_organization_id`,
        org,
      );
      change(next);
    }
    return () => {
      cancelled = true;
    };
    // Existing trades use the actual participant role, not the interface filter.
    // New-trade pages remount when their selected interface role changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org, tradeId]);
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      void tradeRequest<{ items: Partner[] }>(
        `/trading-partners?q=${encodeURIComponent(query)}`,
      )
        .then((value) => {
          if (!cancelled)
            setPartners(
              value.items.filter((item) => item.organization_id !== org),
            );
        })
        .catch((problem) => {
          if (!cancelled) setError(problem.message);
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, org]);
  async function save(): Promise<Trade | null> {
    if (!org || busy.current || conflict) return null;
    const current = tradeRef.current;
    const snapshot = structuredClone(factsRef.current);
    if (current && saved.current === JSON.stringify(snapshot)) return current;
    busy.current = true;
    setPending(true);
    setSaveState("Saving...");
    setError("");
    try {
      const amendment = current?.pending_amendment;
      const view = current
        ? await tradeRequest<Trade>(
            amendment
              ? `/amendments/${amendment.id}/draft`
              : `/trades/${current.trade_id}/draft`,
            org,
            "PATCH",
            {
              base_revision_id: current.current_revision_id,
              changes: snapshot,
            },
            current.etag,
          )
        : await tradeRequest<Trade>("/trades", org, "POST", {
            initiated_by_role: role,
            facts: snapshot,
          });
      apply(view);
      saved.current = JSON.stringify(snapshot);
      setErrors(view.validation_errors);
      setSaveState("Saved");
      failedSnapshot.current = "";
      return view;
    } catch (problem) {
      failedSnapshot.current = JSON.stringify(snapshot);
      setError(
        problem instanceof Error ? problem.message : "Draft save failed",
      );
      if (problem instanceof TradeApiError) {
        setErrors(problem.fields);
        if (problem.status === 412) setConflict(true);
      }
      setSaveState("Save failed");
      return null;
    } finally {
      busy.current = false;
      setPending(false);
      setTick((value) => value + 1);
    }
  }
  useEffect(() => {
    if (
      !trade ||
      conflict ||
      saved.current === JSON.stringify(facts) ||
      failedSnapshot.current === JSON.stringify(facts) ||
      busy.current
    )
      return;
    const timer = setTimeout(() => void save(), 900);
    return () => clearTimeout(timer);
    // Autosave reads the latest facts/ETag from refs, never a stale request closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facts, trade, conflict, tick]);
  async function publish() {
    const current = await save();
    if (!current) return;
    const expires = getValue(
      factsRef.current,
      "commercial_terms.commercial_valid_until",
    );
    setPending(true);
    setError("");
    try {
      await tradeRequest<Trade>(
        current.pending_amendment
          ? `/amendments/${current.pending_amendment.id}/offers`
          : `/trades/${current.trade_id}/offers`,
        org,
        "POST",
        {
          revision_id: current.current_revision_id,
          commercial_valid_until: expires,
        },
        current.etag,
      );
      router.push(`/trades/${current.trade_id}`);
    } catch (problem) {
      setError(
        problem instanceof Error ? problem.message : "Publication failed",
      );
      if (problem instanceof TradeApiError) {
        setErrors(problem.fields);
        if (problem.status === 412) setConflict(true);
      }
    } finally {
      setPending(false);
    }
  }
  async function next() {
    const view = await save();
    if (view) setStep((value) => Math.min(6, value + 1));
  }
  function choosePartner(id: string) {
    const other = role === "SELLER" ? "buyer" : "seller";
    const partner = partners.find((item) => item.organization_id === id);
    let next = setValue(facts, `${other}_organization_id`, id || null);
    next = setValue(
      next,
      `${other}_registration_id`,
      partner?.registrations[0]?.id ?? null,
    );
    next = setValue(next, other === "buyer" ? "bill_to" : "bill_from", {
      organization_id: id || null,
      registration_id: partner?.registrations[0]?.id ?? null,
      billing_address: partner?.trading_locations[0]?.address ?? address(),
    });
    change(next);
  }
  return {
    role,
    step,
    setStep,
    trade,
    facts,
    change,
    saveState,
    errors,
    error,
    conflict,
    profile,
    partners,
    query,
    setQuery,
    pending,
    save,
    next,
    publish,
    choosePartner,
  };
}
