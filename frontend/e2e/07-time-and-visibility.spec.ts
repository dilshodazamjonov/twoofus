// Phones are suspended, switched between apps, and have their own idea of the
// time: polling must stop in the background, resume on return, and progress
// must be estimated with the server's clock, not the phone's.
import { expect, test, type Page } from "@playwright/test";

import {
  api,
  connectDemo,
  fakeProviders,
  owner,
  pinDemo,
  resetRoom,
  routeSpotifyToFake,
  serveFakeArtwork,
  trackErrors,
} from "./helpers";
import { OWNER_STATE } from "./state";

const NOW_PLAYING = "/api/v1/room/now-playing";
const TULIPS = "/api/v1/room/tulips";

async function setVisibility(page: Page, state: "hidden" | "visible") {
  await page.evaluate((value) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => value });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => value === "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

test("in the background nothing polls; back in front, one fresh check", async ({ page }) => {
  test.setTimeout(120_000);
  const errors = trackErrors(page);
  await page.goto("/room");
  await resetRoom(page);
  await connectDemo(page);
  await pinDemo(page, "playing");
  const first = page.waitForResponse((r) => r.url().endsWith(NOW_PLAYING));
  await page.goto("/room");
  await first;
  await page.waitForLoadState("networkidle");

  // Going to the background aborts anything in flight; from then on, silence.
  await setVisibility(page, "hidden");
  const polled: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path === NOW_PLAYING || path === TULIPS) polled.push(path);
  });
  // Longer than both polling intervals (now-playing ~20 s, tulips 25 s).
  await page.waitForTimeout(32_000);
  expect(polled).toEqual([]);

  const back = page.waitForResponse((r) => r.url().endsWith(NOW_PLAYING), { timeout: 5_000 });
  await setVisibility(page, "visible");
  await back;
  await expect(page.getByText(/^Updated just now/)).toBeVisible();

  await resetRoom(page);
  expect(errors).toEqual([]);
});

test("a phone three hours fast, in another time zone, still estimates the song correctly", async ({
  browser,
}, testInfo) => {
  test.setTimeout(120_000);
  const { viewport, userAgent, deviceScaleFactor, isMobile, hasTouch, locale, baseURL } = testInfo.project.use;
  const context = await browser.newContext({
    viewport,
    userAgent,
    deviceScaleFactor,
    isMobile,
    hasTouch,
    locale,
    baseURL,
    storageState: OWNER_STATE,
    timezoneId: "Asia/Tashkent",
  });
  const page = await context.newPage();
  const errors = trackErrors(page);
  await serveFakeArtwork(context);
  await routeSpotifyToFake(page);
  await fakeProviders("POST", "/_control/reset");
  await page.goto("/room");
  await api(page, "DELETE", "/api/v1/providers/connection"); // start from "not connected"
  // The phone's clock runs three hours ahead of the server's (and keeps running).
  await page.clock.install({ time: new Date(Date.now() + 3 * 3600_000) });
  await page.clock.resume();

  await page.goto("/connect");
  await page.getByText("Official connection").click();
  await page.getByRole("button", { name: "Continue to Spotify" }).click();
  await page.getByRole("link", { name: "Agree" }).click();
  await expect(page.getByText("Spotify is connected")).toBeVisible();

  await page.goto("/room");
  const me = page.getByRole("article", { name: owner.name });
  await expect(me).toContainText("Playing");
  await expect(me).toContainText("Fake Spotify Song");
  const bar = me.getByRole("progressbar", { name: "Position in the song" });
  await expect(bar).toBeVisible();
  // The fake says 0:42 of 3:20. Using the phone's clock would put it at the end.
  const position = Number(await bar.getAttribute("aria-valuenow"));
  expect(position).toBeGreaterThanOrEqual(42);
  expect(position).toBeLessThan(80);
  await expect(me).not.toContainText("Checking what's next");
  await expect(page.getByText(/^Updated just now/)).toBeVisible();

  // Dates are shown in her own time zone, never as "in 3 hours" or negative.
  await page.goto("/connect");
  await expect(page.getByText(/^Connected .+ \d{4}\.$/)).toBeVisible();
  await expect(page.getByText(/in \d+ hours?/)).toHaveCount(0);

  await resetRoom(page);
  expect(errors).toEqual([]);
  await context.close();
});
