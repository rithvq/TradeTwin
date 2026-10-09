import type { ComplianceAssessment } from "@/lib/compliance";
import { complianceApiBaseUrl, complianceHeaders } from "@/lib/compliance";
import { documentApiBaseUrl } from "@/lib/documents";
import type { RiskAssessment } from "@/lib/intelligence";
import { intelligenceApiBaseUrl } from "@/lib/intelligence";
import type { Shipment } from "@/lib/shipments";
import { shipmentApiBaseUrl } from "@/lib/shipments";
import type {
  DashboardApiSummary,
  DashboardSummaryData,
  ServiceHealth,
} from "@/types/dashboard";

const platformApiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/services/platform";

const demoSummary = {
  pendingReviews: 6,
  regulationChanges: 1,
  missingDocuments: 4,
  graphRelationships: 148,
  routeAlternatives: 0,
} as const;

export async function fetchDashboardSummary(): Promise<DashboardSummaryData> {
  const [nativeSummary, nativeHealth] = await Promise.all([
    tryFetchJson<DashboardApiSummary>(`${platformApiBaseUrl}/api/v1/dashboard/summary`),
    tryFetchJson<ServiceHealth[]>(`${platformApiBaseUrl}/api/v1/services/health`),
  ]);

  if (nativeSummary) {
    return normalizeNativeSummary(nativeSummary, nativeHealth ?? []);
  }

  return buildCompatibilitySummary();
}

async function buildCompatibilitySummary(): Promise<DashboardSummaryData> {
  const [shipmentsResult, serviceHealth] = await Promise.all([
    tryFetchJson<Shipment[]>(`${shipmentApiBaseUrl}/shipments`),
    fetchServiceHealth(),
  ]);
  const shipments = shipmentsResult ?? [];
  const activeShipments = shipments.filter(
    (shipment) => !["DELIVERED", "CANCELLED"].includes(shipment.status),
  );

  const [assessmentData, riskData] = await Promise.all([
    fetchLatestAssessments(activeShipments),
    fetchLatestRisks(activeShipments),
  ]);

  const complianceAlerts = assessmentData.filter((assessment) =>
    ["CONDITIONALLY_COMPLIANT", "NON_COMPLIANT", "INSUFFICIENT_INFORMATION"].includes(
      assessment.status,
    ),
  ).length;
  const highRiskShipments = riskData.filter(
    (assessment) => assessment.risk_level === "HIGH",
  ).length;
  const unavailableServices = serviceHealth.filter(
    (service) => service.status === "unavailable",
  ).length;
  const liveShipmentData = shipmentsResult !== null;

  return {
    platformStatus:
      unavailableServices === 0
        ? "operational"
        : unavailableServices < serviceHealth.length
          ? "degraded"
          : "unavailable",
    activeShipments: liveShipmentData ? activeShipments.length : 12,
    highRiskShipments: liveShipmentData ? highRiskShipments : 2,
    pendingReviews: demoSummary.pendingReviews,
    complianceAlerts: liveShipmentData ? complianceAlerts : 3,
    regulationChanges: demoSummary.regulationChanges,
    missingDocuments: demoSummary.missingDocuments,
    graphRelationships: demoSummary.graphRelationships,
    routeAlternatives: demoSummary.routeAlternatives,
    serviceHealth,
    dataSource: liveShipmentData ? "mixed" : "mock",
    mockFields: [
      ...(liveShipmentData ? [] : ["activeShipments", "highRiskShipments", "complianceAlerts"]),
      "pendingReviews",
      "regulationChanges",
      "missingDocuments",
      "graphRelationships",
      "routeAlternatives",
    ],
    refreshedAt: new Date().toISOString(),
  };
}

async function fetchLatestAssessments(
  shipments: Shipment[],
): Promise<ComplianceAssessment[]> {
  const results = await Promise.all(
    shipments.slice(0, 30).map(async (shipment) => {
      const assessments = await tryFetchJson<ComplianceAssessment[]>(
        `${complianceApiBaseUrl}/compliance/assessments/${shipment.id}`,
        authHeaders(),
      );
      return assessments?.at(0) ?? null;
    }),
  );
  return results.filter((result): result is ComplianceAssessment => result !== null);
}

async function fetchLatestRisks(shipments: Shipment[]): Promise<RiskAssessment[]> {
  const results = await Promise.all(
    shipments.slice(0, 30).map((shipment) =>
      tryFetchJson<RiskAssessment>(
        `${intelligenceApiBaseUrl}/shipments/${shipment.id}/risk-assessment`,
      ),
    ),
  );
  return results.filter((result): result is RiskAssessment => result !== null);
}

async function fetchServiceHealth(): Promise<ServiceHealth[]> {
  const services = [
    {
      id: "shipment-service",
      label: "Shipment Service",
      url: `${shipmentApiBaseUrl}/ready`,
    },
    {
      id: "compliance-service",
      label: "Compliance Service",
      url: `${complianceApiBaseUrl}/ready`,
    },
    {
      id: "document-service",
      label: "Document Service",
      url: `${documentApiBaseUrl}/ready`,
    },
    {
      id: "intelligence-service",
      label: "Intelligence Service",
      url: `${intelligenceApiBaseUrl}/ready`,
    },
  ];

  return Promise.all(
    services.map(async (service) => ({
      id: service.id,
      label: service.label,
      status: (await tryFetchJson<unknown>(service.url))
        ? ("operational" as const)
        : ("unavailable" as const),
    })),
  );
}

function normalizeNativeSummary(
  summary: DashboardApiSummary,
  serviceHealth: ServiceHealth[],
): DashboardSummaryData {
  const fallbackFields: string[] = [];
  const numberValue = (
    value: number | undefined,
    fallback: number,
    field: string,
  ): number => {
    if (typeof value === "number") {
      return value;
    }
    fallbackFields.push(field);
    return fallback;
  };

  return {
    platformStatus: summary.platform_status ?? "operational",
    activeShipments: numberValue(summary.active_shipments, 12, "activeShipments"),
    highRiskShipments: numberValue(summary.high_risk_shipments, 2, "highRiskShipments"),
    pendingReviews: numberValue(summary.pending_reviews, 6, "pendingReviews"),
    complianceAlerts: numberValue(summary.compliance_alerts, 3, "complianceAlerts"),
    regulationChanges: numberValue(summary.regulation_changes, 1, "regulationChanges"),
    missingDocuments: numberValue(summary.missing_documents, 4, "missingDocuments"),
    graphRelationships: numberValue(summary.graph_relationships, 148, "graphRelationships"),
    routeAlternatives: numberValue(summary.route_alternatives, 5, "routeAlternatives"),
    serviceHealth,
    dataSource: fallbackFields.length > 0 ? "mixed" : "live",
    mockFields: fallbackFields,
    refreshedAt: new Date().toISOString(),
  };
}

function authHeaders(): HeadersInit | undefined {
  return complianceHeaders();
}

async function tryFetchJson<T>(
  url: string,
  headers?: HeadersInit,
): Promise<T | null> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), 2500);

  try {
    const response = await fetch(url, {
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  } finally {
    globalThis.clearTimeout(timeout);
  }
}
