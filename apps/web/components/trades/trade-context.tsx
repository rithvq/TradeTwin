"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Building2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { tradeRequest, type Me, type ReferenceData } from "@/lib/trades";

type Context = {
  me: Me;
  org: string;
  role: "SELLER" | "BUYER";
  refs: ReferenceData;
  reload: () => Promise<void>;
  setOrg: (value: string) => void;
  setRole: (value: "SELLER" | "BUYER") => void;
};
const TradeContext = createContext<Context | null>(null);
export function useTradeContext() {
  const value = useContext(TradeContext);
  if (!value) throw new Error("Trade context missing");
  return value;
}

export function TradeArea({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  const [org, selectOrg] = useState("");
  const [role, selectRole] = useState<"SELLER" | "BUYER">("SELLER");
  const [viewRole, selectViewRole] = useState("SELLER");
  const [error, setError] = useState("");
  async function reload() {
    try {
      const [profile, data] = await Promise.all([
        tradeRequest<Me>("/me"),
        tradeRequest<ReferenceData>("/reference-data"),
      ]);
      const stored = localStorage.getItem("tt-commercial-org");
      selectOrg(
        profile.memberships.some((member) => member.organization_id === stored)
          ? stored!
          : (profile.memberships[0]?.organization_id ?? ""),
      );
      setMe(profile);
      setRefs(data);
      setError("");
    } catch (problem) {
      setError(
        problem instanceof Error
          ? problem.message
          : "Unable to load organisations",
      );
    }
  }
  useEffect(() => {
    void reload();
    const stored = localStorage.getItem("tt-commercial-role");
    if (stored === "BUYER") selectRole(stored);
  }, []);
  function setOrg(value: string) {
    localStorage.setItem("tt-commercial-org", value);
    selectOrg(value);
  }
  function setRole(value: "SELLER" | "BUYER") {
    localStorage.setItem("tt-commercial-role", value);
    selectRole(value);
    selectViewRole(value);
  }
  const member = me?.memberships.find((item) => item.organization_id === org);
  const views = [
    ...(member?.capabilities.some((c) => c.startsWith("SELLER_"))
      ? [{ id: "SELLER", label: "Seller" }]
      : []),
    ...(member?.capabilities.some((c) => c.startsWith("BUYER_"))
      ? [{ id: "BUYER", label: "Buyer" }]
      : []),
    ...(member?.capabilities.includes("CARRIER_DISPATCHER")
      ? [{ id: "CARRIER_DISPATCHER", label: "Carrier dispatcher" }]
      : []),
    ...(member?.capabilities.includes("DRIVER")
      ? [{ id: "DRIVER", label: "Driver" }]
      : []),
    ...(member?.capabilities.includes("BUYER_FINANCE")
      ? [{ id: "BUYER_FINANCE", label: "Buyer finance" }]
      : []),
    ...(member?.capabilities.includes("SELLER_FINANCE")
      ? [{ id: "SELLER_FINANCE", label: "Seller finance" }]
      : []),
  ];
  useEffect(() => {
    const supported = views.some((v) => v.id === viewRole);
    if (!supported && views[0]) {
      selectViewRole(views[0].id);
      if (views[0].id.startsWith("BUYER")) selectRole("BUYER");
      if (views[0].id.startsWith("SELLER")) selectRole("SELLER");
    }
  }, [org, member, viewRole]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <main className="tt-page">
      <header className="tt-context-header">
        <div className="mx-auto max-w-[1320px] space-y-4 px-4 py-5 sm:px-6">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 text-sm text-secondary"
          >
            <ArrowLeft className="size-4" />
            Dashboard
          </Link>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="tt-kicker">Shipments / Commercial agreements</p>
              <h1 className="mt-1 text-2xl font-semibold">Trade workspace</h1>
              <p className="mt-2 text-sm text-secondary">
                Operational timezone: Asia/Kolkata (IST)
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" asChild>
                <Link href="/trades">Trades</Link>
              </Button>
              {member?.capabilities.some(
                (c) => c === "DRIVER" || c === "CARRIER_DISPATCHER",
              ) && (
                <Button variant="outline" asChild>
                  <Link href="/shipments/tasks">Transport tasks</Link>
                </Button>
              )}
              <Button variant="outline" asChild>
                <Link href="/trades/organization">
                  <Building2 className="size-4" />
                  Business profile
                </Link>
              </Button>
              {member?.permissions.some(
                (p) => p.permission_code === "trade.create",
              ) && (
                <Button asChild>
                  <Link href="/trades/new">
                    <Plus className="size-4" />
                    Create trade
                  </Link>
                </Button>
              )}
            </div>
          </div>
          {me ? (
            <div className="grid gap-3 border-t border-line pt-4 sm:grid-cols-[minmax(0,1fr)_auto]">
              <label className="text-sm font-medium">
                Current organisation
                <select
                  className="mt-1 block w-full rounded border p-2"
                  value={org}
                  onChange={(event) => setOrg(event.target.value)}
                >
                  <option value="">No organisation selected</option>
                  {me.memberships.map((item) => (
                    <option
                      key={item.organization_id}
                      value={item.organization_id}
                    >
                      {item.legal_name ?? "Incomplete business profile"}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset className="min-w-0">
                <legend className="text-sm font-medium">Interface role</legend>
                <div className="mt-1 flex flex-wrap rounded border border-line">
                  {views.map((item) => (
                    <button
                      type="button"
                      key={item.id}
                      aria-pressed={viewRole === item.id}
                      onClick={() => {
                        selectViewRole(item.id);
                        if (item.id.startsWith("BUYER")) {
                          localStorage.setItem("tt-commercial-role", "BUYER");
                          selectRole("BUYER");
                        }
                        if (item.id.startsWith("SELLER")) {
                          localStorage.setItem("tt-commercial-role", "SELLER");
                          selectRole("SELLER");
                        }
                        if (["DRIVER", "CARRIER_DISPATCHER"].includes(item.id))
                          router.push("/shipments/tasks");
                      }}
                      className={`min-h-10 px-4 text-sm ${viewRole === item.id ? "bg-accent text-white" : "bg-surface"}`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </fieldset>
              <p className="text-xs text-secondary sm:col-span-2">
                Capabilities:{" "}
                {member?.capabilities.join(", ") ||
                  "No commercial capabilities"}{" "}
                | Registrations:{" "}
                {member?.registrations
                  .map((item) => `${item.gstin} (${item.verification_status})`)
                  .join(", ") || "None declared"}
              </p>
            </div>
          ) : null}
        </div>
      </header>
      <div className="mx-auto max-w-[1320px] px-4 py-6 sm:px-6">
        {error ? (
          <p role="alert" className="text-red-800">
            {error}{" "}
            <button className="underline" onClick={() => void reload()}>
              Retry
            </button>
          </p>
        ) : !me || !refs ? (
          <p role="status">Loading your organisations...</p>
        ) : (
          <TradeContext.Provider
            value={{ me, refs, org, role, setOrg, setRole, reload }}
          >
            {children}
          </TradeContext.Provider>
        )}
      </div>
    </main>
  );
}
