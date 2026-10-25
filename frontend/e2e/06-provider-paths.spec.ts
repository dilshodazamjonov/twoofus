// The real Spotify and Yandex code paths, end to end in the browser, against
// the local fake of both services (backend/tests/fakes/providers.py): the
// backend's real adapters run unmodified; only the far end is fake.
import { expect, test, type Page } from "@playwright/test";

import {
  PARTNER,
  enableSharing,
  ensureAlone,
  fakeProviders,
  invitePartner,
  owner,
  resetRoom,
  routeSpotifyToFake,
  serveFakeArtwork,
  trackErrors,
} from "./helpers";

/** The backend caches for 2 s in e2e runs; reloading is the UI's next poll. */
async function nextPoll(page: Page) {
  await page.waitForTimeout(2_500);
  await page.reload();
}

test("Spotify sign-in, Yandex device approval, live states, privacy and revocation", async ({
  page,
  browser,
}, testInfo) => {
  test.setTimeout(240_000);
  const ownerErrors = trackErrors(page);
  await serveFakeArtwork(page.context());
  await fakeProviders("POST", "/_control/reset");
  await page.goto("/room");
  await ensureAlone(page, browser, testInfo);
  await resetRoom(page);

  // ----- the owner connects Spotify through the (fake) consent page ----------------------
  await routeSpotifyToFake(page);
  await page.goto("/connect");
  await page.getByText("Official connection").click();
  await page.getByRole("button", { name: "Continue to Spotify" }).click();
  await expect(page.getByText("Local test fake of Spotify's consent page.")).toBeVisible();
  await expect(page.getByText("user-read-currently-playing")).toBeVisible();
  await page.getByRole("link", { name: "Agree" }).click();
  await expect(page).toHaveURL(/\/connect\?connect=spotify&result=connected$/);
  await expect(page.getByText("Spotify is connected")).toBeVisible();
  const spotifyEvents = (await fakeProviders("GET", "/_control/log")).map((e: { event: string }) => e.event);
  expect(spotifyEvents).toContain("pkce_verified");
  expect(spotifyEvents).not.toContain("client_secret_sent");
  await enableSharing(page);

  // ----- the partner joins and connects Yandex Music with a device code ---------------------
  const partner = await invitePartner(page, browser, testInfo);
  const p = partner.page;
  await serveFakeArtwork(partner.context);
  await p.getByText("Unofficial, may stop working").click();
  await p.getByRole("button", { name: "Get a code from Yandex" }).click();
  await expect(p.getByRole("link", { name: /Open ya\.ru/ })).toHaveAttribute("href", "https://ya.ru/device");
  await expect(p.getByLabel(/^Code: \d( \d){6}$/)).toBeVisible();
  // She approves on Yandex's own page (the fake's control API stands in for that tap).
  expect((await fakeProviders("POST", "/_control/yandex/approve")).updated).toBe(1);
  await expect(p.getByText("Yandex Music is connected.")).toBeVisible({ timeout: 20_000 });
  await enableSharing(p);

  // ----- both see each other's real-path cards -----------------------------------------------
  await page.goto("/room");
  const partnerCard = page.getByRole("article", { name: PARTNER.name });
  await expect(partnerCard).toContainText("Fake Yandex Song");
  await expect(partnerCard).toContainText("Fixture Singer");
  await expect(partnerCard.getByRole("link", { name: /Open in Yandex Music/ })).toHaveAttribute(
    "href",
    "https://music.yandex.ru/album/1193829/track/10994777",
  );
  await expect(partnerCard.locator('img[src^="https://avatars.yandex.net/"]')).toBeVisible();

  await p.goto("/room");
  const ownerCard = p.getByRole("article", { name: owner.name });
  await expect(ownerCard).toContainText("Playing");
  await expect(ownerCard).toContainText("Fake Spotify Song");
  await expect(ownerCard.getByRole("link", { name: /Play on Spotify/ })).toHaveAttribute(
    "href",
    "https://open.spotify.com/track/4fakeTrackId0000000000",
  );
  await expect(ownerCard.locator('img[src="https://i.scdn.co/image/fake-cover-300"]')).toBeVisible();
  await expect(ownerCard).toContainText("estimated");

  // ----- the owner's Spotify states, as the partner sees them ---------------------------------
  const states: Array<[string, (card: typeof ownerCard) => Promise<void>]> = [
    ["paused", async (card) => {
      await expect(card).toContainText("Paused");
      await expect(card).toContainText("Fake Spotify Song");
    }],
    ["idle", async (card) => {
      await expect(card).toContainText("Not playing");
      await expect(card).not.toContainText("Fake Spotify Song");
    }],
    ["private", async (card) => {
      await expect(card).toContainText("Private session");
      await expect(card).not.toContainText("Fake Spotify Song");
    }],
    ["no_artwork", async (card) => {
      await expect(card).toContainText("No Cover Album");
      await expect(card.locator('img[src*="scdn.co"]')).toHaveCount(0);
    }],
    ["unknown_position", async (card) => {
      await expect(card).toContainText("Fake Spotify Song");
      await expect(card).not.toContainText("estimated");
    }],
    ["playing", async (card) => {
      await expect(card).toContainText("Playing");
    }],
    ["rate_limited", async (card) => {
      await expect(card).toContainText("Last confirmed");
      await expect(card).not.toContainText("Playing");
    }],
  ];
  for (const [scenario, check] of states) {
    await fakeProviders("PUT", "/_control/spotify", { scenario, retry_after: 2 });
    await nextPoll(p);
    await check(ownerCard);
  }

  // ----- privacy: the owner stops sharing while the partner's room stays open ------------------
  await fakeProviders("PUT", "/_control/spotify", { scenario: "playing" });
  await nextPoll(p);
  await expect(ownerCard).toContainText("Fake Spotify Song");
  await page.goto("/settings");
  await page.getByRole("switch", { name: /^Share my music/ }).click();
  await expect(page.getByRole("switch", { name: /^Share my music/ })).toHaveAttribute("aria-checked", "false");
  // No reload: the partner's next regular poll (requested after the switch) must
  // carry nothing, and what was on screen must go.
  const toggledAt = Date.now();
  const next = await p.waitForResponse(
    (r) => r.url().endsWith("/api/v1/room/now-playing") && r.request().timing().startTime >= toggledAt,
    { timeout: 30_000 },
  );
  const body = await next.json();
  expect(body.partner.playback).toMatchObject({ status: "private", source: null, track_title: null });
  expect(JSON.stringify(body.partner)).not.toContain("Fake Spotify Song");
  await expect(ownerCard).toContainText("Not sharing");
  await expect(ownerCard).not.toContainText("Fake Spotify Song");
  await expect(ownerCard.locator("img")).toHaveCount(0);
  await enableSharing(page);

  // ----- Yandex states, as the owner sees them -----------------------------------------------------
  for (const [scenario, text] of [
    ["no_device", "Not playing"],
    ["playing", "Fake Yandex Song"],
    ["go_away", /Last confirmed|asked to slow down/],
  ] as const) {
    await fakeProviders("PUT", "/_control/yandex", { scenario });
    await page.waitForTimeout(3_500); // past the cache and the previous step's backoff
    await page.goto("/room");
    await expect(partnerCard).toContainText(text);
  }
  const ynison = (await fakeProviders("GET", "/_control/log")).filter((e: { service: string }) => e.service === "ynison");
  expect(ynison.some((e: { event: string }) => e.event === "unexpected_message")).toBe(false); // read-only

  // ----- a revoked Spotify grant: reconnect needed, nothing invented ------------------------------
  await fakeProviders("PUT", "/_control/spotify", { scenario: "revoked" });
  await fakeProviders("POST", "/_control/expire-access");
  await nextPoll(page);
  const myCard = page.getByRole("article", { name: owner.name });
  await expect(myCard).toContainText("Reconnect needed");
  await expect(myCard.getByRole("link", { name: "Reconnect Spotify" })).toBeVisible();
  await nextPoll(p);
  await expect(ownerCard).toContainText("Unavailable");

  // ----- disconnecting: Yandex confirms the revocation; Spotify has no such API -------------------
  await p.goto("/connect");
  await p.getByRole("button", { name: "Disconnect" }).click();
  await p.getByRole("dialog").getByRole("button", { name: "Disconnect" }).click();
  await expect(p.getByText("Yandex Music confirmed the sign-in is cancelled.", { exact: false })).toBeVisible();
  const yandexEvents = (await fakeProviders("GET", "/_control/log")).map((e: { event: string }) => e.event);
  expect(yandexEvents).toContain("token_revoked");

  await page.goto("/connect");
  await page.getByRole("button", { name: "Disconnect" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Disconnect" }).click();
  await expect(page.getByText("Spotify disconnected and our copy deleted.", { exact: false })).toBeVisible();

  await resetRoom(page, p);
  await fakeProviders("POST", "/_control/reset");
  expect(ownerErrors).toEqual([]);
  expect(partner.errors).toEqual([]);
  await partner.context.close();
});
