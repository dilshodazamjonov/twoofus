import { expect, test } from "@playwright/test";

test("manifest, icons and service worker headers", async ({ request }) => {
  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBe(true);
  expect(manifest.headers()["content-type"]).toContain("application/manifest+json");
  const body = await manifest.json();
  expect(body).toMatchObject({ name: "JustTheTwoOfUs", display: "standalone", start_url: "/room", scope: "/" });
  const sizes = body.icons.map((icon: { sizes: string; purpose: string }) => `${icon.sizes}/${icon.purpose}`);
  expect(sizes).toEqual(expect.arrayContaining(["192x192/any", "512x512/any", "512x512/maskable"]));
  for (const icon of body.icons) expect((await request.get(icon.src)).ok()).toBe(true);
  expect((await request.get("/apple-icon.png")).headers()["content-type"]).toBe("image/png");

  const sw = await request.get("/sw.js");
  expect(sw.ok()).toBe(true);
  expect(sw.headers()["cache-control"]).toContain("no-cache");
  expect(sw.headers()["content-type"]).toContain("javascript");
  expect(await sw.text()).toContain('url.pathname.startsWith("/api/")');

  const page = await request.get("/");
  const html = await page.text();
  expect(html).toContain('rel="manifest" href="/manifest.webmanifest"');
  expect(html).toContain('rel="apple-touch-icon"');
  expect(html).toContain("viewport-fit=cover");
  expect(page.headers()["x-frame-options"]).toBe("DENY");
});

test("service worker: offline fallback, and nothing private is ever cached", async ({ page, context, browserName }) => {
  test.skip(browserName !== "chromium", "Service worker interception is checked in Chromium");
  await page.goto("/room");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload(); // now controlled by the worker
  await expect(page.getByText(/^Updated/)).toBeVisible();
  await expect.poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);

  const cached = await page.evaluate(async () => {
    const urls: string[] = [];
    for (const name of await caches.keys()) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) urls.push(new URL(request.url).pathname);
    }
    return urls;
  });
  expect(cached).toContain("/offline.html");
  expect(cached.filter((path) => path.startsWith("/api/"))).toEqual([]);
  expect(cached.filter((path) => ["/room", "/settings", "/connect", "/"].includes(path))).toEqual([]);

  await context.setOffline(true);
  await page.goto("/settings").catch(() => undefined);
  await expect(page.getByRole("heading", { name: "You’re offline" })).toBeVisible();
  await context.setOffline(false);
});
