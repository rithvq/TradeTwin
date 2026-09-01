# Demo Walkthrough

Use this sequence for project evaluation.

1. Start Docker.

```powershell
docker compose up -d --build
powershell -ExecutionPolicy Bypass -File scripts/health-check.ps1
```

2. Open `http://localhost:3000`.

3. Create the India to UAE to Germany shipment from the home page.

4. Confirm the shipment has two consignments:

- Lithium batteries from India to Germany.
- Consumer electronics from India to UAE.

5. Open the Documents page and upload demo documents. Use
   `data/demo-battery-safety-certificate.txt` for the safety certificate.

6. Extract uploaded document metadata.

7. Return to shipment details and record a UAE `UNLOADED` event for consumer
   electronics.

8. Run compliance evaluation.

9. Show independent results:

- Consumer electronics: UAE import treatment.
- Lithium batteries: UAE transit treatment.

10. Publish the demo UAE lithium transit safety-certificate regulation update.

11. Run impact analysis and show the affected shipment.

12. Compare alternate routes and show the recommended compliant route.

13. Export the compliance report as HTML or PDF.

14. Explain the evidence trace and the legal disclaimer in the report.
