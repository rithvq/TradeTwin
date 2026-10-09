"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Bell,
  Boxes,
  Building2,
  CircleUserRound,
  FileSearch,
  LayoutDashboard,
  LoaderCircle,
  Network,
  Search,
  ShieldCheck,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { apiFetch, type Shipment } from "@/lib/shipments";

import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const shipmentMatch = pathname.match(/^\/shipments\/([^/]+)/);
  const shipmentId = shipmentMatch?.[1];
  const isDocuments = pathname.endsWith("/documents");
  if (pathname === "/login") return <>{children}</>;

  return (
    <div className="min-h-screen bg-surface">
      <header className="sticky top-0 z-50 border-b border-line bg-surface/95 backdrop-blur-xl">
        <div className="flex min-h-16 w-full flex-wrap items-center gap-2 px-3 py-2 sm:flex-nowrap sm:gap-4 sm:px-6 sm:py-0 xl:px-0">
          <Link
            href="/dashboard"
            className="flex shrink-0 items-center gap-3 xl:w-[300px] xl:justify-center"
            aria-label="TradeTwin dashboard"
          >
            <span className="relative flex size-9 items-center justify-center rounded border border-line bg-soft text-ink">
              <Network className="size-5" aria-hidden="true" />
            </span>
            <span className="hidden sm:block">
              <span className="block text-sm font-semibold text-ink">TradeTwin</span>
              <span className="block text-xs text-muted">Compliance operations</span>
            </span>
          </Link>

          <nav className="order-last flex w-full items-center gap-1 sm:order-none sm:ml-3 sm:w-auto xl:ml-0" aria-label="Primary navigation">
            <ShellLink
              href="/dashboard"
              active={pathname.startsWith("/dashboard")}
              icon={LayoutDashboard}
              label="Dashboard"
            />
            <ShellLink href="/" active={pathname === "/"} icon={Boxes} label="Shipments" />
            {shipmentId ? (
              <ShellLink
                href={`/shipments/${shipmentId}`}
                active={!isDocuments}
                icon={ShieldCheck}
                label="Digital twin"
              />
            ) : null}
            {shipmentId ? (
              <ShellLink
                href={`/shipments/${shipmentId}/documents`}
                active={isDocuments}
                icon={FileSearch}
                label="Evidence"
              />
            ) : null}
          </nav>

          <div className="ml-auto flex items-center gap-1.5 xl:pr-6">
            <ShipmentSearch />

            <TradeTwinDemoLauncher />

            <NotificationsSheet />
            <UserDialog />
          </div>
        </div>
      </header>

      {children}

      <footer className="border-t border-line bg-surface">
        <div className="mx-auto flex max-w-[1500px] flex-col gap-2 px-4 py-5 text-xs text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span>TradeTwin prototype environment</span>
          <span>Decision support only. Not legal or customs advice.</span>
        </div>
      </footer>
    </div>
  );
}

function TradeTwinDemoLauncher() {
  const router = useRouter();
  const [isLaunching, setIsLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function launchDemo() {
    setError(null);
    setIsLaunching(true);
    try {
      const shipment = await apiFetch<Shipment>("/demo/seed", { method: "POST" });
      router.push(`/shipments/${shipment.id}`);
    } catch (launchError) {
      setError(
        launchError instanceof Error
          ? launchError.message
          : "The demo scenario could not be prepared.",
      );
    } finally {
      setIsLaunching(false);
    }
  }

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={isLaunching}
            onClick={launchDemo}
            aria-label={isLaunching ? "Preparing demo" : "TradeTwin Demo"}
            className="shrink-0 border-l border-line text-xs text-secondary xl:w-auto xl:px-3"
          >
            {isLaunching ? (
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <Building2 className="size-4 text-muted" aria-hidden="true" />
            )}
            <span className="hidden xl:inline">{isLaunching ? "Preparing demo" : "TradeTwin Demo"}</span>
          </Button>
        </TooltipTrigger>
        <TooltipContent>Run the seeded demo scenario</TooltipContent>
      </Tooltip>

      {error ? (
        <div
          role="alert"
          className="fixed right-4 top-20 z-[100] flex w-[min(92vw,420px)] items-start gap-3 rounded border border-red-400/25 bg-red-50 p-4 shadow-2xl"
        >
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-red-800">Demo unavailable</p>
            <p className="mt-1 text-sm leading-5 text-red-800/80">{error}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => setError(null)}
            aria-label="Dismiss demo error"
            className="shrink-0 text-red-800"
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </>
  );
}

function ShipmentSearch() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const shipmentsQuery = useQuery({
    queryKey: ["shipments"],
    queryFn: () => apiFetch<Shipment[]>("/shipments"),
    enabled: open,
  });
  const results = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const shipments = shipmentsQuery.data ?? [];
    if (!normalizedQuery) {
      return shipments.slice(0, 8);
    }
    return shipments
      .filter((shipment) =>
        [
          shipment.shipment_reference,
          shipment.domestic?.origin.city ?? shipment.exporter_country,
          shipment.domestic?.destination.city ?? shipment.importer_country,
        ].some((value) => value.toLowerCase().includes(normalizedQuery)),
      )
      .slice(0, 8);
  }, [query, shipmentsQuery.data]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            <Button
              type="button"
              variant="outline"
              className="h-9 w-9 px-0 lg:w-56 lg:justify-start lg:px-3 lg:text-muted"
              aria-label="Search shipments"
            >
              <Search className="size-4 shrink-0" aria-hidden="true" />
              <span className="hidden lg:inline">Search shipments</span>
            </Button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent>Search shipments</TooltipContent>
      </Tooltip>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Find a shipment</DialogTitle>
          <DialogDescription>
            Search by shipment reference or dispatch and delivery city.
          </DialogDescription>
        </DialogHeader>
        <label className="relative block">
          <span className="sr-only">Shipment search</span>
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted"
            aria-hidden="true"
          />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="TT- reference or city"
            className="h-11 w-full rounded border border-line pl-10 pr-3 text-sm outline-none"
          />
        </label>
        <div className="max-h-80 divide-y divide-line overflow-y-auto">
          {shipmentsQuery.isLoading ? (
            <p className="py-6 text-sm text-muted">Loading shipments...</p>
          ) : null}
          {shipmentsQuery.isError ? (
            <p className="py-6 text-sm text-red-800">Shipment search is unavailable.</p>
          ) : null}
          {!shipmentsQuery.isLoading && !shipmentsQuery.isError && results.length === 0 ? (
            <p className="py-6 text-sm text-muted">No matching shipments.</p>
          ) : null}
          {results.map((shipment) => (
            <DialogClose asChild key={shipment.id}>
              <Link
                href={`/shipments/${shipment.id}`}
                className="flex items-center justify-between gap-4 py-3 text-sm hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <span>
                  <span className="block font-medium text-ink">
                    {shipment.shipment_reference}
                  </span>
                  <span className="mt-1 block text-xs text-muted">
                    {shipment.domestic ? `${shipment.domestic.origin.city} to ${shipment.domestic.destination.city}` : `${shipment.exporter_country} to ${shipment.importer_country}`}
                  </span>
                </span>
                <span className="text-xs text-muted">{shipment.status}</span>
              </Link>
            </DialogClose>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function NotificationsSheet() {
  const links = [
    { href: "/dashboard/compliance?view=violations", label: "Compliance alerts" },
    { href: "/dashboard/regulations?view=changes", label: "Regulation changes" },
    { href: "/dashboard/evidence?view=reviews", label: "Pending evidence reviews" },
  ];

  return (
    <Sheet>
      <Tooltip>
        <TooltipTrigger asChild>
          <SheetTrigger asChild>
            <Button type="button" variant="ghost" size="icon" aria-label="Open notifications">
              <Bell className="size-4" aria-hidden="true" />
            </Button>
          </SheetTrigger>
        </TooltipTrigger>
        <TooltipContent>Operational queues</TooltipContent>
      </Tooltip>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Operational queues</SheetTitle>
          <SheetDescription>Open the live workspace for items that may need review.</SheetDescription>
        </SheetHeader>
        <nav className="mt-6 divide-y divide-line" aria-label="Operational queues">
          {links.map((link) => (
            <SheetClose asChild key={link.href}>
              <Link
                href={link.href}
                className="flex min-h-14 items-center justify-between text-sm text-secondary hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                {link.label}
                <Activity className="size-4 text-muted" aria-hidden="true" />
              </Link>
            </SheetClose>
          ))}
        </nav>
      </SheetContent>
    </Sheet>
  );
}

function UserDialog() {
  const [error, setError] = useState("");
  const [signingOut, setSigningOut] = useState(false);
  const principal = useQuery({
    queryKey: ["principal"],
    queryFn: async () => {
      const response = await fetch("/api/auth/session", { cache: "no-store" });
      if (!response.ok) throw new Error("Session expired");
      return response.json() as Promise<{ id: string; name: string; email: string; role: string }>;
    },
    retry: false,
  });
  async function signOut() {
    setSigningOut(true);
    setError("");
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error();
      window.sessionStorage.removeItem("tradetwin-token");
      window.location.replace("/login");
    } catch {
      setError("Sign-out failed. Please try again.");
      setSigningOut(false);
    }
  }
  return (
    <Dialog>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            <Button type="button" variant="ghost" size="icon" aria-label="Open user menu">
              <CircleUserRound className="size-5" aria-hidden="true" />
            </Button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent>Your profile</TooltipContent>
      </Tooltip>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{principal.data?.name ?? "Your account"}</DialogTitle>
          <DialogDescription>
            {principal.isError ? "Your session has expired. Sign in to continue." :
              principal.data?.email || "Loading your profile..."}
          </DialogDescription>
        </DialogHeader>
        {error ? <p role="alert" className="text-sm text-red-800">{error}</p> : null}
        <div className="border-y border-line py-4 text-sm text-secondary">
          Personal workspace
        </div>
        {principal.isError ? (
          <Button asChild><Link href="/login">Sign in</Link></Button>
        ) : (
          <Button variant="outline" onClick={signOut} disabled={signingOut}>
            {signingOut ? "Signing out..." : "Sign out"}
          </Button>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ShellLink({
  href,
  active,
  icon: Icon,
  label,
}: {
  href: string;
  active: boolean;
  icon: LucideIcon;
  label: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          href={href}
          aria-label={label}
          className={cn(
            "flex h-9 items-center gap-2 rounded px-2.5 text-sm font-medium transition-colors sm:px-3",
            active
              ? "bg-soft text-ink"
              : "text-secondary hover:bg-soft hover:text-ink",
          )}
        >
          <Icon className="size-4 shrink-0" aria-hidden="true" />
          <span className="hidden 2xl:inline">{label}</span>
        </Link>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
