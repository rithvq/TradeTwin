import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { DomesticShipmentForm as ShipmentForm } from "@/components/domestic-shipment-form";

export default function NewShipmentPage() {
  return (
    <main className="tt-page">
      <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        <Link
          href="/dashboard/shipments"
          className="inline-flex items-center gap-2 text-sm font-medium text-secondary hover:text-accent"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          Shipment Twin
        </Link>
        <div className="mt-5">
          <ShipmentForm />
        </div>
      </div>
    </main>
  );
}
