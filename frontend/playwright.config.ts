import { defineConfig, devices, type PlaywrightTestProject } from "@playwright/test";

import { OWNER_STATE } from "./e2e/state";
import { existsSync } from "node:fs";
import path from "node:path";

// Run through ../scripts/e2e.sh, which starts isolated backend + frontend
// servers (temporary database, DEMO data) and sets E2E_* variables.
// Playwright loads this file as CommonJS: __dirname is available.
const root = `${path.resolve(__dirname, "..")}/`;

// WebKit (Safari's engine) needs a few system libraries. Without sudo,
// scripts/install-webkit-deps.sh unpacks them into .tools/webkit-deps and
// scripts/playwright-webkit.sh launches WebKit with them. E2E_WEBKIT=native
// uses a system-wide installation instead (`sudo npx playwright install-deps`).
const localWebkit = existsSync(`${root}.tools/webkit-deps/root`);
const webkit: PlaywrightTestProject[] =
  localWebkit || process.env.E2E_WEBKIT === "native"
    ? [
        {
          name: "iphone-webkit",
          dependencies: ["setup"],
          use: {
            ...devices["iPhone 15"],
            storageState: OWNER_STATE,
            launchOptions: localWebkit ? { executablePath: `${root}scripts/playwright-webkit.sh` } : {},
          },
        },
      ]
    : [];

export default defineConfig({
  testDir: "e2e",
  // One shared server and one room: tests run in order, one at a time.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3200",
    trace: "retain-on-failure",
    locale: "en-US",
    timezoneId: "Europe/Berlin",
  },
  // The owner signs in once (setup) and the tests reuse that session: signing
  // in for every test would trip the backend's login rate limit, as it should.
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "iphone-chromium",
      dependencies: ["setup"],
      use: { ...devices["iPhone 15"], browserName: "chromium", storageState: OWNER_STATE },
    },
    {
      name: "desktop-chromium",
      dependencies: ["setup"],
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, storageState: OWNER_STATE },
    },
    ...webkit,
  ],
});
