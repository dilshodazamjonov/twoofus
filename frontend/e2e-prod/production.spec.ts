// The deployed app as a phone sees it: HTTPS origin, strict CSP, Secure
// __Host- cookies, a working service worker, and no demo anywhere.
import { expect, test } from "@playwright/test";

const PASSWORD = process.env.PROD_OWNER_PASSWORD ?? "";

test("sign in, the room, the connect page and the PWA on the production stack", async ({ page, context }) => {
  expect(PASSWORD, "run through ../scripts/prod-check.sh").not.toBe("");
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && !/Failed to load resource/.test(message.text())) problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(error.message));

  await page.goto("/room");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Froom$/);
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/room$/);
  await expect(page.getByText("Not connected").first()).toBeVisible();

  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name === "__Host-twoofus_session");
  expect(session?.secure).toBe(true);
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Lax");
  expect(cookies.some((c) => c.name === "twoofus_session")).toBe(false);

  // Spotify and Yandex are offered; the demo is not in this build at all.
  await page.goto("/connect");
  await expect(page.getByText("Official connection")).toBeVisible();
  await expect(page.getByText("Unofficial, may stop working")).toBeVisible();
  await expect(page.getByText("Demo songs")).toHaveCount(0);

  // Continue to Spotify goes to Spotify with this origin's HTTPS callback.
  let authorize: URL | null = null;
  await page.route("https://accounts.spotify.com/**", async (route) => {
    authorize = new URL(route.request().url());
    await route.fulfill({ status: 200, contentType: "text/html", body: "<p>stub</p>" });
  });
  const origin = new URL(page.url()).origin;
  await page.getByText("Official connection").click();
  await page.getByRole("button", { name: "Continue to Spotify" }).click();
  await expect.poll(() => authorize?.searchParams.get("redirect_uri")).toBe(
    `${origin}/api/v1/providers/spotify/callback`,
  );

  // The service worker installs over HTTPS and controls the app after a reload.
  await page.goto("/room");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
  const cached = await page.evaluate(async () => {
    const urls: string[] = [];
    for (const name of await caches.keys()) {
      for (const request of await (await caches.open(name)).keys()) urls.push(new URL(request.url).pathname);
    }
    return urls;
  });
  expect(cached.filter((path) => path.startsWith("/api/") || path === "/room" || path === "/settings")).toEqual([]);

  expect(problems).toEqual([]);
});
