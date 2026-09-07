# Shipment Service

Owner of Phase 1 shipment lifecycle state, consignments, route legs, timeline events, and the shipment graph projection.

## Endpoints

- `GET /health`
- `POST /shipments`
- `GET /shipments`
- `GET /shipments/{id}`
- `DELETE /shipments/{id}`
- `POST /shipments/{id}/consignments`
- `POST /shipments/{id}/route-legs`
- `POST /shipments/{id}/events`
- `GET /shipments/{id}/timeline`
- `GET /shipments/{id}/graph`

## Demo Seed

On startup the service seeds a demonstration shipment for India to UAE to Germany:

- Consignment A: Lithium batteries from India to Germany
- Consignment B: Consumer electronics from India to UAE

The seeded timeline records creation in India, loading both consignments, arrival in UAE, and unloading consumer electronics in UAE.
