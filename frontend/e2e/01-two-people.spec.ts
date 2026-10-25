import { expect, test } from "@playwright/test";

import {
  PARTNER,
  api,
  connectDemo,
  enableSharing,
  ensureAlone,
  invitePartner,
  owner,
  resetRoom,
  trackErrors,
} from "./helpers";

test("two people: invite, connect, share, see each other, send a tulip, and privacy after revoking", async ({
  page,
  browser,
}, testInfo) => {
  const ownerErrors = trackErrors(page);

  // ----- the owner (signed in by auth.setup.ts) is alone in the room --------------------
  await page.goto("/room");
  await ensureAlone(page, browser, testInfo);
  await resetRoom(page);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Nobody else yet" })).toBeVisible();
  await expect(page.getByText("Not connected").first()).toBeVisible();

  // ----- invitation: created by the owner, accepted by the partner -----------------------
  const partner = await invitePartner(page, browser, testInfo);
  const p = partner.page;
  await expect(p.getByRole("heading", { name: "Connect your music" })).toBeVisible();

  // ----- the partner connects (DEMO) - connecting does NOT share -------------------------
  await connectDemo(p);
  await page.goto("/room");
  const partnerCard = page.getByRole("article", { name: PARTNER.name });
  await expect(partnerCard).toContainText("Not sharing");

  // ----- the owner tries Spotify: authorise URL is checked, then they decline -------------
  await page.goto("/connect");
  const origin = new URL(page.url()).origin;
  await page.getByText("Official connection").click();
  let authorizeUrl: URL | null = null;
  await page.route("https://accounts.spotify.com/**", async (route) => {
    authorizeUrl = new URL(route.request().url());
    await route.fulfill({ status: 200, contentType: "text/html", body: "<p>Spotify (stubbed by the test)</p>" });
  });
  await page.getByRole("button", { name: "Continue to Spotify" }).click();
  await expect.poll(() => authorizeUrl?.pathname).toBe("/authorize");
  const params = authorizeUrl!.searchParams;
  expect(params.get("client_id")).toBe(process.env.E2E_SPOTIFY_CLIENT_ID);
  expect(params.get("response_type")).toBe("code");
  expect(params.get("code_challenge_method")).toBe("S256");
  expect(params.get("scope")).toBe("user-read-currently-playing");
  expect(params.get("redirect_uri")).toBe(`${origin}/api/v1/providers/spotify/callback`);
  expect(params.get("state")?.length).toBeGreaterThan(30);
  // Simulate Spotify sending the person back after they declined.
  await page.goto(`/api/v1/providers/spotify/callback?error=access_denied&state=${params.get("state")}`);
  await expect(page).toHaveURL(/\/connect\?connect=spotify&result=access_denied/);
  await expect(page.getByText("Spotify wasn't connected")).toBeVisible();

  // ----- the owner connects DEMO instead; both turn sharing on (consent dialog) ----------
  await connectDemo(page);
  await enableSharing(p);
  await enableSharing(page);

  // ----- the room shows both people -----------------------------------------------------
  await api(p, "PUT", "/api/v1/providers/demo/scenario", { scenario: "playing" });
  await page.goto("/room");
  await expect(partnerCard).toContainText("Playing");
  await expect(partnerCard).toContainText("Paper Lanterns");
  await expect(partnerCard).toContainText("Demo");
  await expect(page.getByRole("article", { name: owner.name })).toContainText(`Visible to ${PARTNER.name}`);
  await expect(page.getByText(/^Updated/)).toBeVisible();

  // ----- tulips: the partner sends one, the owner is told once ---------------------------
  await p.goto("/room");
  await p.getByRole("button", { name: "Send a tulip" }).click();
  await expect(p.getByText(`Tulip sent to ${owner.name}.`)).toBeVisible();
  await page.reload();
  await expect(page.getByText(`${PARTNER.name} sent you a tulip.`)).toBeVisible();
  await expect(page.getByText(`From ${PARTNER.name},`)).toBeVisible();

  // ----- privacy: the partner revokes sharing; the owner's API response has nothing ------
  await p.goto("/settings");
  await p.getByRole("switch", { name: /Share my music with/ }).click();
  await expect(p.getByRole("switch", { name: /Share my music with/ })).toHaveAttribute("aria-checked", "false");
  const responsePromise = page.waitForResponse((r) => r.url().endsWith("/api/v1/room/now-playing"));
  await page.reload();
  const body = await (await responsePromise).json();
  expect(body.partner.playback).toMatchObject({
    status: "private",
    source: null,
    track_title: null,
    artist_names: [],
    album: null,
    artwork_url: null,
    track_url: null,
    progress_ms: null,
  });
  expect(JSON.stringify(body.partner)).not.toContain("Paper Lanterns");
  await expect(partnerCard).toContainText("Not sharing");
  await expect(partnerCard).not.toContainText("Paper Lanterns");

  // ----- the partner deletes their account; the owner is alone again --------------------
  await p.goto("/settings");
  await p.getByRole("button", { name: "Delete my account…" }).click();
  await p.getByLabel("Password", { exact: true }).fill(PARTNER.password);
  await p.getByRole("button", { name: "Delete forever" }).click();
  await expect(p).toHaveURL(/\/\?deleted=1$/);
  await expect(p.getByText("Your account was deleted")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Nobody else yet" })).toBeVisible();

  await resetRoom(page);
  expect(ownerErrors).toEqual([]);
  expect(partner.errors).toEqual([]);
  await partner.context.close();
});
