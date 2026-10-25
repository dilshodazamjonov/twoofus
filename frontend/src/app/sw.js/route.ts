// Serves /sw.js. Prerendered at build time with this build's id, so every
// deploy ships a byte-different worker and installed apps offer to refresh.
//
// Caching policy:
// * /api/* and every cross-origin request (album art, Spotify, Yandex) are
//   never touched: private data and provider content are never cached.
// * Page navigations always go to the network and are never stored. Only when
//   the network fails is the static /offline.html (no personal data) shown.
// * Only hashed build assets and our own icons/brand files are cached, in a
//   per-build cache that is deleted when a new version activates.
const BUILD_ID = process.env.TWOOFUS_BUILD_ID ?? "dev";

const SCRIPT = `/* JustTheTwoOfUs service worker, build ${BUILD_ID} */
const STATIC_CACHE = "twoofus-static-${BUILD_ID}";
const OFFLINE_URL = "/offline.html";
const PRECACHE = [OFFLINE_URL, "/icons/icon-192.png", "/icon.svg"];
const CACHEABLE = ["/_next/static/", "/icons/", "/brand/", "/demo/"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      cache.addAll(PRECACHE.map((url) => new Request(url, { cache: "reload" }))),
    ),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names.filter((name) => name.startsWith("twoofus-") && name !== STATIC_CACHE).map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  if (url.pathname === "/icon.svg" || CACHEABLE.some((prefix) => url.pathname.startsWith(prefix))) {
    event.respondWith(cacheFirst(request));
  }
});

async function cacheFirst(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok && response.type === "basic") cache.put(request, response.clone());
  return response;
}
`;

export function GET() {
  return new Response(SCRIPT, {
    headers: {
      "Content-Type": "application/javascript; charset=utf-8",
      "Cache-Control": "no-cache, no-store, must-revalidate",
    },
  });
}
