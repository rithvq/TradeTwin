# Demo Walkthrough

The navbar **TradeTwin Demo** opens the integrated India freight walkthrough.
Sign in with your normal profile; no organisation or approval role is required
to launch it. Demo records are private to that profile's simulation workspace.

1. Start Docker.

```powershell
docker compose up -d --build
powershell -ExecutionPolicy Bypass -File scripts/health-check.ps1
```

2. Open `http://localhost:3000`.

3. Sign in, then click **TradeTwin Demo**. Setup runs in the document worker.
   It creates an accepted Bengaluru–Chennai agreement, three completed historical
   consignments and one new consignment with 70 units remaining to move.

4. Explore the feature links. They open the ordinary commercial, document,
   freight, compliance, graph, corridor, receipt, payment and replay screens.
   The sample PDF uses real encrypted storage, scanning and AUTO extraction.
   Release evidence uses separate, explicitly reviewed synthetic documents.

5. Inspect the distance/time route comparisons, state-corridor history and
   reasons for each alternative. The retained topology, prices, driver reports
   and permissions evidence are labelled SIMULATION. They are not live highway,
   government verification, traffic or safety assurances. Configured live ORS
   routing and weather can still be requested in the ordinary route optimizer.

6. Use **Run next demo step** to publish an independently reviewed, simulated
   direct-road closure and recompute alternatives. Accept the alternate freight
   offer through distinct simulation payer and carrier actors. Fixed quotes are
   not automatically repriced.

7. Run pickup release, pickup, departure release and departure separately.
   Open **Pickup journey** or **Departure journey** to inspect the existing
   seven-stage dispatch projection. Evaluations, independent reviews, driver
   acknowledgments and single-use authorizations use the normal movement gate.

8. Complete arrival, receipt, inspection and declared payment. Payment records
   are declarations, not bank settlement. Executable in-transit recovery remains
   unsupported; the demo does not fabricate a successful recovery.

9. **Start fresh demo** creates a successor workspace and retains earlier records.
   Each session permits new guided actions for ten minutes; expired evidence
   cannot be reused by a step. **Exit demo** restores the previous organisation
   and interface-role preference. No production approval, driver or organisation
   administrator permissions are granted to the profile.

The **Original shipment scenario** button preserves the earlier domestic
shipment demo and its legacy screens. The bounded Phase 7 qualification scenario
also remains unchanged.

Deployment requires `IN_APP_DEMO_ENABLED=true` (included in `.env.example` for
local Compose), the document worker, encrypted storage and a working scanner.
`DOCUMENT_DEMO_ENABLED` can remain false: generated imports are restricted to
active, registered simulation commands and their synthetic identities. Failed
partial setup is retained and is never blindly retried.

Acceptance: `python scripts/integrated-demo-browser-check.py` uses disposable
databases, genuine encryption/parser jobs and a test scanner transport. It checks
profile isolation, all feature links, mobile layout, all eight guided steps,
consumed pickup/departure authorizations, retained history and context restoration.
It does not certify malware-detection quality or live provider availability.
