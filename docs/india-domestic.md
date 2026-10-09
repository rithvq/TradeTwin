# India Domestic Workflow

TradeTwin's primary workflow is now domestic Indian road shipments, including
interstate and intrastate movements. All new shipments use Indian dispatch and
delivery locations and INR. Each consignment has its own delivery stop and total
consignment value, including tax. Locations contain state/UT, city and PIN code.
PIN validation checks format, not a postal-directory lookup.

## Supported Checks

The initial rules cover document readiness for ordinary taxable supplies by a
registered consignor using road transport. Confirm these assumptions in the form
or through the recommended questions. Job work, stock transfers, exempt goods,
special handling and other unsupported cases return insufficient information.

- Tax invoice evidence for the supported supply scenario.
- E-way bill evidence for ordinary interstate consignments exceeding INR 50,000.
  The threshold is applied per consignment, not to the combined shipment total.
- Intrastate e-way bill applicability requires reviewer confirmation against the
  applicable state notification. A national threshold is not silently substituted.
- Document quantity, value, HSN, and dispatch/delivery-state conflicts.

Rules are versioned in `services/compliance-service/app/rules/india-domestic.v1.json`.
Their effective date identifies this application's initial rule-set release;
it is not the original commencement date of the underlying legislation.
Sources: [official e-way bill FAQ](https://docs.ewaybillgst.gov.in/html/faq_new.html)
and [CBIC invoice rules](https://cbic-gst.gov.in/gst-invoice-rules.html).

A COMPLIANT result means the supported document checks passed. File extraction
does not establish authenticity, portal registration, e-way bill validity, GST
payment, correct tax rate or compliance with every applicable law. There is no
live GST/e-way bill filing or verification integration. State exceptions and
sector-specific requirements need separately reviewed rule packs.

## Demo

Use **Load demo scenario** or **TradeTwin Demo**. The route is Chennai (Tamil Nadu)
to Bengaluru (Karnataka) to Pune (Maharashtra). Stationery worth INR 20,000 is
delivered in Bengaluru; cotton shirts worth INR 75,000 remain at the hub for Pune.
The four events are creation, loading, hub arrival, and stationery delivery.

Upload a tax invoice for each consignment, extract it, and evaluate. The shirts
require an e-way bill under the supported rule; the stationery does not reach
the threshold. Upload and extract the shirts' e-way bill, then reevaluate and
inspect evidence. Demo-document buttons simulate document metadata; their
results are demonstrations, not verification of uploaded files.

**Publish demo policy** introduces an interstate packing-list requirement and
reruns affected active shipments. This is labelled company-policy demo data,
not a new Indian government regulation.

## Other Modules

- The graph represents Indian locations and independent delivery states.
- Reports include domestic cities and preserve assessment/evidence records.
- Route review uses the entered route and distance, with a 40 km/h driving-time
  assumption. It does not invent alternate roads, charge customs duty, or apply
  FTAs. Verified alternate-route data is a subsequent integration.
- HSN suggestions remain a small demo taxonomy, with human review.
- Domestic risk uses its own reproducible synthetic baseline in
  `services/intelligence-service/app/domestic_risk.py`. Inputs are distance,
  stops, INR value and missing HSN count. Outputs simulate document review,
  document exceptions and handling delay. No measured accuracy is claimed.
- The existing API names `customs_status`, `countries`, `inspection_probability`,
  `rejection_probability` and `expected_clearance_delay_hours` remain for client
  compatibility; domestic screens translate them into the domestic meanings above.

## Migration and Running

Startup adds nullable domestic JSON/JSONB columns to shipments, consignments and
route legs. Existing international records are retained with no inferred state
or city. The new form and creation API require domestic details. Older scenario
code and rules are retained for historical compatibility and future expansion.
Profile isolation, OAuth, document storage and infrastructure remain in place.

```powershell
docker compose up -d --build
docker compose ps
```

Open http://localhost:3000. Keep the existing `.env` and OAuth settings. Do not
remove volumes during this migration.

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/smoke-test.py --local
.venv\Scripts\python.exe scripts/profile-security-check.py
```

The smoke check uses temporary databases and exercises document upload,
extraction, independent results, evidence, policy impact, reports and delivery.
The profile check uses separate accounts and verifies access boundaries.
