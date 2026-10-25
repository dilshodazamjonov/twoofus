// The web app manifest. Generated per request so the installed app's name
// follows the backend's APP_NAME (GET /api/v1/config); falls back to the
// default name if the backend is unreachable.
import { connection } from "next/server";

import { DEFAULT_APP_NAME } from "@/lib/app-name";

const BACKEND = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

async function appName(): Promise<string> {
  // Server to server: the same proxy secret the /api rewrite adds (src/proxy.ts).
  const secret = process.env.TWOOFUS_PROXY_SECRET;
  try {
    const response = await fetch(`${BACKEND}/api/v1/config`, {
      cache: "no-store",
      signal: AbortSignal.timeout(1500),
      headers: secret ? { "x-twoofus-proxy-auth": secret } : {},
    });
    if (response.ok) {
      const body = (await response.json()) as { app_name?: unknown };
      if (typeof body.app_name === "string" && body.app_name.trim()) return body.app_name.trim().slice(0, 40);
    }
  } catch {
    // fall through to the default
  }
  return DEFAULT_APP_NAME;
}

export async function GET() {
  await connection();
  const name = await appName();
  const manifest = {
    id: "/",
    name,
    short_name: name,
    description: "Now playing, shared.",
    start_url: "/room",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#FFF9F5",
    theme_color: "#FFF9F5",
    categories: ["music", "lifestyle"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
  return new Response(JSON.stringify(manifest), {
    headers: {
      "Content-Type": "application/manifest+json; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
