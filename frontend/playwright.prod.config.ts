import { defineConfig, devices } from "@playwright/test";

// Browser pass against the real production stack (run by ../scripts/prod-check.sh):
// https://127.0.0.1:8443 behind Caddy, ENVIRONMENT=production, no demo UI.
// Chromium trusts only this run's test certificate (by its public-key hash), so
// HTTPS, Secure cookies and the service worker behave as on a real domain.
const spki = process.env.PROD_SPKI ?? "";

export default defineConfig({
  testDir: "e2e-prod",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: "test-results/prod",
  use: {
    baseURL: process.env.PROD_ORIGIN ?? "https://127.0.0.1:8443",
    trace: "retain-on-failure",
    locale: "en-US",
    timezoneId: "Europe/Berlin",
  },
  projects: [
    {
      name: "iphone-chromium-prod",
      use: {
        ...devices["iPhone 15"],
        browserName: "chromium",
        launchOptions: { args: [`--ignore-certificate-errors-spki-list=${spki}`] },
      },
    },
  ],
});
