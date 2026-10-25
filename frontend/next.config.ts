import type { NextConfig } from "next";

// The browser only ever talks to this Next.js origin. Every /api/* request is
// proxied to FastAPI, so session cookies stay first-party (important for
// Safari/iOS PWAs) and the Spotify OAuth callback lands on the same origin as
// the session cookie. No CORS is needed or enabled.
//
// Note: rewrites are resolved when the app is built, so BACKEND_INTERNAL_URL
// must be set at build time for `next build` / `next start`.
const backend = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // Lets scripts/smoke.sh build into a separate folder without touching .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
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
};

export default nextConfig;
