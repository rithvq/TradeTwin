"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { activeDemo, DEMO_CHANGED, exitDemo } from "@/lib/demo-center";

export function DemoBanner() {
  const router = useRouter();
  const [selection, select] = useState<ReturnType<typeof activeDemo>>(null);
  useEffect(() => {
    const read = () => select(activeDemo());
    read();
    window.addEventListener(DEMO_CHANGED, read);
    return () => window.removeEventListener(DEMO_CHANGED, read);
  }, []);
  if (!selection) return null;
  return (
    <aside
      aria-label="Active simulation"
      className="flex flex-wrap items-center justify-between gap-3 border-b border-teal-200 bg-teal-50 px-6 py-2 text-sm text-teal-950"
    >
      <span className="font-semibold">Simulation workspace</span>
      <div className="flex gap-4">
        <Link
          href={`/demo/${selection.id}`}
          className="font-semibold underline underline-offset-4"
        >
          Return to demo
        </Link>
        <button
          type="button"
          className="underline underline-offset-4"
          onClick={() => {
            exitDemo();
            router.push("/dashboard");
            router.refresh();
          }}
        >
          Exit demo
        </button>
      </div>
    </aside>
  );
}
