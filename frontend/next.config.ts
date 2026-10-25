import type { NextConfig } from "next";

// The browser only ever talks to this Next.js origin. Every /api/* request is
// proxied to FastAPI, so session cookies stay first-party (important for
// Safari/iOS PWAs) and the Spotify OAuth callback lands on the same origin as
// the session cookie. No CORS is needed or enabled.
//
// Note: rewrites are resolved when the app is built, so BACKEND_INTERNAL_URL
// must be set at build time for `next build` / `next start`.
const backend = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

// Identifies this build inside the service worker script, so every deploy
// ships a byte-different /sw.js and installed apps notice the update.
const buildId = process.env.APP_BUILD_ID || Date.now().toString(36);

// The development-only demo UI is compiled in for `next dev` and for the
// e2e/smoke builds (TWOOFUS_DEMO_UI=1), never into a plain production build.
const demoUi = process.env.TWOOFUS_DEMO_UI ?? (process.env.NODE_ENV === "production" ? "0" : "1");

// Page headers. The Content-Security-Policy (with a per-request nonce) is set
// in src/proxy.ts; HSTS is set by the HTTPS edge (Caddy, see deploy/). The API
// sets its own, stricter headers in FastAPI.
const pageHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  // Lets scripts build into a separate folder (.next-smoke, .next-e2e) without touching .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // The Docker image runs the minimal standalone server (deploy/).
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  // Every page is rendered per request (src/app/layout.tsx), so each response
  // can carry its own CSP nonce. That rules out Cache Components / partial
  // prerendering, whose static shells cannot carry a per-request nonce.
  poweredByHeader: false,
  env: { TWOOFUS_BUILD_ID: buildId, TWOOFUS_DEMO_UI: demoUi },
  turbopack: {
    // "@demo-ui" is the only way into the demo UI: the real module, or a stub.
    resolveAlias: {
      "@demo-ui": demoUi === "1" ? "./src/components/demo/index.ts" : "./src/components/demo/off.ts",
    },
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  async headers() {
    return [
      { source: "/((?!api/).*)", headers: pageHeaders },
      {
        // Always revalidate the service worker so updates are picked up.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
        ],
      },
    ];
  },
};

export default nextConfig;
