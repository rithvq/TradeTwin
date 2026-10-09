export const shipmentApiBaseUrl =
  process.env.NEXT_PUBLIC_SHIPMENT_SERVICE_URL ?? "/api/services/shipment";

export type Consignment = {
  domestic?: { destination: IndianLocation; consignment_value: number; eway_bill_required?: boolean | null } | null;
  id: string;
  shipment_id: string;
  product_name: string;
  product_description: string;
  quantity: number;
  declared_value: string;
  currency: string;
  country_of_origin: string;
  destination_country: string;
  proposed_hs_code: string | null;
  customs_status: string;
};

export type RouteLeg = {
  domestic?: { origin: IndianLocation; destination: IndianLocation; distance_km: number } | null;
  id: string;
  shipment_id: string;
  sequence_number: number;
  origin_country: string;
  destination_country: string;
  transport_mode: string;
  carrier_name: string;
};

export type Shipment = {
  domestic?: { origin: IndianLocation; destination: IndianLocation; consignor_name: string; consignee_name: string; movement_reason: string; registered_consignor?: boolean | null; ordinary_goods?: boolean | null } | null;
  id: string;
  shipment_reference: string;
  exporter_country: string;
  importer_country: string;
  transport_mode: string;
  planned_departure_at: string;
  planned_arrival_at: string;
  status: string;
  created_at: string;
  consignments: Consignment[];
  route_legs: RouteLeg[];
};

export type ShipmentEvent = {
  id: string;
  shipment_id: string;
  consignment_id: string | null;
  event_type: string;
  location_country: string;
  occurred_at: string;
  metadata: Record<string, unknown>;
};

export type ShipmentGraph = {
  nodes: Array<{ id: string; label: string; type: string }>;
  edges: Array<{ id: string; source: string; target: string; label: string }>;
};

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${shipmentApiBaseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function deleteShipment(shipmentId: string): Promise<void> {
  const response = await fetch(`${shipmentApiBaseUrl}/shipments/${shipmentId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
}

export function displayStatus(status: string): string {
  return status
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export type IndianLocation = { state: string; city: string; pincode: string };
export function locationLabel(location: IndianLocation): string {
  return `${location.city}, ${location.state}`;
}
export function shipmentRoute(shipment: Shipment): string {
  return shipment.domestic ? `${locationLabel(shipment.domestic.origin)} to ${locationLabel(shipment.domestic.destination)}` : `${shipment.exporter_country} to ${shipment.importer_country}`;
}
