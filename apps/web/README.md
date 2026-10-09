# TradeTwin Web

Next.js, TypeScript, and Tailwind CSS frontend for the TradeTwin platform.

The shipment intake form supports editable shipment details, any country entered by the
user, multiple route legs, and multiple consignments. Use **Load demo scenario** to
populate the original India to UAE to Germany evaluation scenario.

The operations UI uses a shared dark workspace shell. Shipment details combine an
interactive orbital event timeline with the existing Neo4j-backed React Flow graph,
compliance results, document evidence, intelligence panels, and route controls.

The primary navigation dashboard is available at `/dashboard`. It uses TanStack
Query to read current microservice health and shipment-derived metrics, provides an
eight-module orbital interface on desktop, and switches to a complete module grid on
mobile. Metrics without aggregate backend endpoints are labeled as demo values.

## Local Development

```bash
npm install
npm run dev
```
