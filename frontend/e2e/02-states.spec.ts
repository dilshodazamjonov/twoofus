import { expect, test } from "@playwright/test";

import { api, connectDemo, newPerson, owner, pinDemo, resetRoom, signIn, trackErrors } from "./helpers";
import { OWNER_STATE, SIGNED_OUT } from "./state";

// Card states replayed through the real backend pipeline with the
// development-only demo scenarios (no real provider involved).
test("my card in every provider state, and never 'Playing' for stale data", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/room");
  await resetRoom(page);
  await connectDemo(page);
  const card = page.getByRole("article", { name: owner.name });

  await pinDemo(page, "playing");
  await page.goto("/room");
  await expect(card).toContainText("Playing");
  await expect(card.getByRole("progressbar", { name: "Position in the song" })).toHaveAttribute(
    "aria-valuetext",
    /estimated$/,
  );

  // 429 from the provider: the last song stays, clearly marked as not current.
  await pinDemo(page, "rate_limited");
  await page.reload();
  await expect(card).toContainText(/Last confirmed/);
  await expect(card).not.toContainText("Playing");
  await expect(card.getByRole("progressbar")).toHaveCount(0);

  for (const [scenario, text] of [
    ["paused", "Paused"],
    ["idle", "Not playing"],
    ["non_music", "Something other than music"],
    ["private_session", "Private session"],
    ["unreachable", /Last confirmed|isn't responding/],
  ] as const) {
    await pinDemo(page, scenario);
    await page.reload();
    await expect(card, scenario).toContainText(text);
  }

  await pinDemo(page, "reauth_required");
  await page.reload();
  await expect(card).toContainText("Reconnect needed");
  await card.getByRole("link", { name: "Reconnect Demo" }).click();
  await expect(page).toHaveURL(/\/connect$/);
  await expect(page.getByText("Needs reconnecting")).toBeVisible();

  await resetRoom(page);
  expect(errors).toEqual([]);
});

test("offline: a calm banner, then recovery", async ({ page, context }) => {
  await page.goto("/room");
  await expect(page.getByText(/^Updated/)).toBeVisible();
  await context.setOffline(true);
  // Shown when the browser reports going offline, or at the latest when the next
  // poll fails (some engines never report it; navigator.onLine is only a hint).
  const banner = page.getByText("You're offline.", { exact: true });
  await expect(banner).toBeVisible({ timeout: 30_000 });
  await context.setOffline(false);
  await expect(banner).toBeHidden({ timeout: 30_000 });
  await expect(page.getByText(/^Updated/)).toBeVisible();
});

test("opened while the server is unreachable: recovers by itself", async ({ page }) => {
  await page.route("**/api/v1/auth/session", (route) => route.abort("internetdisconnected"));
  await page.goto("/room");
  await expect(page.getByRole("heading", { name: /Can't reach/ })).toBeVisible();
  await page.unroute("**/api/v1/auth/session");
  await page.evaluate(() => window.dispatchEvent(new Event("online"))); // the connection is back
  await expect(page.getByText(/^Updated/)).toBeVisible();
});

test.describe("signed out", () => {
  test.use({ storageState: SIGNED_OUT });

  test("a session ended elsewhere sends you to sign in, gently", async ({ page, browser }, testInfo) => {
    await signIn(page);
    const sessions = await api(page, "GET", "/api/v1/me/sessions");
    const mine = sessions.body.sessions.find((s: { current: boolean }) => s.current);
    // The same person, on another device, signs this browser out from Settings.
    const other = await newPerson(browser, testInfo, OWNER_STATE);
    await other.page.goto("/settings");
    expect((await api(other.page, "DELETE", `/api/v1/me/sessions/${mine.id}`)).status).toBe(204);

    await page.goto("/settings");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Fsettings&expired=1$/);
    await expect(page.getByText("Please sign in again")).toBeVisible();
    await other.context.close();
  });

  test("signing in rejects wrong passwords without revealing which part was wrong", async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByLabel("Username").fill(owner.username);
  await page.getByLabel("Password", { exact: true }).fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  const alert = page.locator("form").getByRole("alert");
  await expect(alert).toHaveText("That username and password don't match.");
  await page.getByLabel("Username").fill("nobody-here");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(alert).toHaveText("That username and password don't match.");
  });

  test("an expired or used invitation is explained kindly", async ({ page }) => {
    await page.goto("/invite#token=thisisnotarealinvitationtoken000");
    await expect(page.getByText("This invitation can't be used")).toBeVisible();
    await page.goto("/invite");
    await expect(page.getByText("This link looks incomplete")).toBeVisible();
  });
});
