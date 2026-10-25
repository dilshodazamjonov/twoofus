import { expect, type Browser, type BrowserContext, type Page, type TestInfo } from "@playwright/test";

export const owner = {
  username: process.env.E2E_OWNER_USERNAME ?? "alex",
  name: process.env.E2E_OWNER_NAME ?? "Alex",
  password: process.env.E2E_OWNER_PASSWORD ?? "",
};
export const PARTNER = { username: "sam", name: "Sam", password: "a lovely long password" };

/** Collect uncaught page errors and console errors (asserted empty at the end of a test). */
export function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => {
    // WebKit reports Next.js prefetches it cancels during a full page load as
    // "… ?_rsc=… due to access control checks." That's the cancellation, not an app error.
    if (/_rsc=.*access control checks/.test(error.message)) return;
    errors.push(`pageerror: ${error.message}`);
  });
  page.on("console", (message) => {
    // Failed requests we provoke on purpose (401/403/404/429) are logged by browsers as console errors.
    if (message.type() === "error" && !/Failed to load resource/.test(message.text())) errors.push(message.text());
  });
  return errors;
}

/** A fresh browser context shaped like the current project's device. */
export async function newPerson(
  browser: Browser,
  testInfo: TestInfo,
  storageState?: string,
): Promise<{ context: BrowserContext; page: Page; errors: string[] }> {
  const { viewport, userAgent, deviceScaleFactor, isMobile, hasTouch, locale, timezoneId, baseURL } = testInfo.project.use;
  const context = await browser.newContext({
    viewport,
    userAgent,
    deviceScaleFactor,
    isMobile,
    hasTouch,
    locale,
    timezoneId,
    baseURL,
    storageState,
  });
  const page = await context.newPage();
  return { context, page, errors: trackErrors(page) };
}

export async function signIn(page: Page, username = owner.username, password = owner.password) {
  await page.goto("/room");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Froom/);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/room$/);
}

/** Call the API from inside the page (same origin, CSRF cookie echoed like the app does). */
export async function api(page: Page, method: string, path: string, body?: unknown) {
  return page.evaluate(
    async ({ method, path, body }) => {
      const csrf = document.cookie.match(/(?:^|; )(?:__Host-)?twoofus_csrf=([^;]+)/)?.[1];
      const response = await fetch(path, {
        method,
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return { status: response.status, body: response.status === 204 ? null : await response.json() };
    },
    { method, path, body },
  );
}

/** The owner creates an invitation in Settings; the partner accepts it in their own browser. */
export async function invitePartner(ownerPage: Page, browser: Browser, testInfo: TestInfo) {
  await ownerPage.goto("/settings#person");
  await ownerPage.getByRole("button", { name: /Create (invitation|a new) link/ }).click();
  const link = (await ownerPage.getByLabel("Invitation link").textContent())?.trim() ?? "";
  expect(link).toMatch(/\/invite#token=[A-Za-z0-9_-]{20,}$/);

  const partner = await newPerson(browser, testInfo);
  await partner.page.goto(new URL(link).pathname + new URL(link).hash);
  await expect(partner.page.getByRole("heading", { name: `${owner.name} invited you` })).toBeVisible();
  await partner.page.getByLabel("Your name").fill(PARTNER.name);
  await partner.page.getByLabel("Username").fill(PARTNER.username);
  await partner.page.getByLabel("Password", { exact: true }).fill(PARTNER.password);
  await partner.page.getByLabel("Confirm password").fill(PARTNER.password);
  await partner.page.getByRole("button", { name: "Create account" }).click();
  await expect(partner.page).toHaveURL(/\/connect$/);
  return partner;
}

export async function connectDemo(page: Page) {
  await page.goto("/connect");
  await expect(page.getByRole("heading", { name: "Music service" })).toBeVisible();
  const { body } = await api(page, "GET", "/api/v1/providers");
  if (body.connection?.provider === "demo" && body.connection.status === "active") return;
  if (body.connection) {
    await api(page, "DELETE", "/api/v1/providers/connection");
    await page.reload();
  }
  await page.getByText("Demo songs").click();
  await page.getByRole("button", { name: "Use demo songs" }).click();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
}

/**
 * Make sure the owner is alone in the room (a previous failed test may have
 * left a partner behind): sign in as that partner and delete the account.
 */
export async function ensureAlone(ownerPage: Page, browser: Browser, testInfo: TestInfo) {
  if (!ownerPage.url().startsWith("http")) await ownerPage.goto("/room");
  const room = await api(ownerPage, "GET", "/api/v1/room");
  if (room.body.members.length < 2) return;
  const leftover = await newPerson(browser, testInfo);
  await leftover.page.goto("/sign-in");
  await expect(leftover.page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  const login = await api(leftover.page, "POST", "/api/v1/auth/login", {
    username: PARTNER.username,
    password: PARTNER.password,
  });
  expect(login.status, "a leftover partner from another test").toBe(200);
  expect((await api(leftover.page, "DELETE", "/api/v1/me", { password: PARTNER.password })).status).toBe(204);
  await leftover.context.close();
}

export async function enableSharing(page: Page) {
  await page.goto("/settings");
  const toggle = page.getByRole("switch", { name: /^Share my music/ });
  await expect(toggle).toBeEnabled();
  if ((await toggle.getAttribute("aria-checked")) === "true") return;
  await toggle.click();
  const confirm = page.getByRole("button", { name: "Start sharing" });
  if (await confirm.isVisible().catch(() => false)) await confirm.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
}

export async function pinDemo(page: Page, scenario: string) {
  const result = await api(page, "PUT", "/api/v1/providers/demo/scenario", { scenario });
  expect(result.status).toBe(200);
}

/** Leave the shared server as we found it: no partner, owner disconnected and not sharing. */
export async function resetRoom(ownerPage: Page, partnerPage?: Page) {
  if (partnerPage) {
    const deleted = await api(partnerPage, "DELETE", "/api/v1/me", { password: PARTNER.password });
    expect([204, 401]).toContain(deleted.status);
  }
  await api(ownerPage, "PUT", "/api/v1/me/sharing", { share_now_playing: false });
  await api(ownerPage, "DELETE", "/api/v1/providers/connection");
  await api(ownerPage, "DELETE", "/api/v1/invitations/current");
}

/** The local fake of Spotify and Yandex that scripts/e2e.sh starts (backend/tests/fakes/providers.py). */
export const FAKE_PROVIDERS = process.env.E2E_FAKE_PROVIDERS ?? "http://127.0.0.1:8300";

export async function fakeProviders(method: "GET" | "PUT" | "POST", path: string, body?: unknown) {
  const response = await fetch(`${FAKE_PROVIDERS}${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  expect(response.ok, `fake providers ${method} ${path}`).toBe(true);
  return response.json();
}

const FAKE_COVER = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#F6DADD"/><stop offset="1" stop-color="#813F59"/></linearGradient></defs><rect width="300" height="300" fill="url(#g)"/><circle cx="150" cy="150" r="60" fill="#FFF9F5" opacity=".85"/></svg>`;

/**
 * The fake provider data points at real CDN hosts (i.scdn.co, avatars.yandex.net),
 * so the page's CSP is exercised with realistic URLs; the images themselves are
 * served locally and nothing leaves the machine.
 */
export async function serveFakeArtwork(context: BrowserContext) {
  await context.route(/^https:\/\/(i\.scdn\.co|avatars\.yandex\.net)\//, (route) =>
    route.fulfill({ status: 200, contentType: "image/svg+xml", body: FAKE_COVER }),
  );
}

/** The browser's trip to Spotify's consent page is answered by the fake. */
export async function routeSpotifyToFake(page: Page) {
  await page.route("https://accounts.spotify.com/authorize**", async (route) => {
    const search = new URL(route.request().url()).search;
    const response = await route.fetch({ url: `${FAKE_PROVIDERS}/spotify/accounts/authorize${search}` });
    await route.fulfill({ response });
  });
}
