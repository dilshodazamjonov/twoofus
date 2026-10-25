// Demo-provider endpoints (development only). Kept apart from endpoints.ts so
// production bundles, built without the demo UI, never include them.
import { apiRequest } from "./client";
import type { ConnectionOut, DemoScenario, DemoScenarioOut } from "./types";

type Signal = { signal?: AbortSignal };

export const demoApi = {
  connect: () => apiRequest<ConnectionOut>("/api/v1/providers/demo/connect", { method: "POST" }),
  scenario: (o: Signal = {}) => apiRequest<DemoScenarioOut>("/api/v1/providers/demo/scenario", o),
  setScenario: (scenario: DemoScenario) =>
    apiRequest<DemoScenarioOut>("/api/v1/providers/demo/scenario", { method: "PUT", body: { scenario } }),
};
