// Runs before every page and API request (Next.js "proxy", formerly middleware).
//
// * Pages: a fresh CSP nonce per request (src/lib/csp.ts); Next.js applies it
//   to its scripts because every page is rendered per request.
// * Signed-in pages: visitors without any session cookie go straight to
//   sign-in instead of loading the app shell first. This is only a shortcut:
//   the API enforces authentication on every request.
// * /api/*: when TWOOFUS_PROXY_SECRET is set (server-side only, never sent to
//   browsers), it is added to the request the /api rewrite forwards to
//   FastAPI, which then refuses anything that did not come through here or
//   through Caddy. A client-supplied copy of the header is always dropped.
import { NextResponse, type NextRequest } from "next/server";

import { contentSecurityPolicy, newNonce } from "@/lib/csp";

const SESSION_COOKIES = ["__Host-twoofus_session", "twoofus_session"];
const SIGNED_IN_PAGES = new Set(["/room", "/connect", "/settings"]);
const PROXY_AUTH_HEADER = "x-twoofus-proxy-auth";
const CLIENT_IP_HEADERS = ["x-forwarded-for", "x-real-ip", "forwarded"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname.startsWith("/api/")) return forwardToApi(request);

  if (SIGNED_IN_PAGES.has(pathname) && !SESSION_COOKIES.some((name) => request.cookies.has(name))) {
    const url = request.nextUrl.clone();
    url.pathname = "/sign-in";
    url.search = `?next=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  }

  const csp = contentSecurityPolicy(newNonce(), { dev: process.env.NODE_ENV === "development" });
  const headers = new Headers(request.headers);
  headers.set("content-security-policy", csp);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

function forwardToApi(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete(PROXY_AUTH_HEADER);
  // The browser must not choose the client IP the API's rate limits see:
  // without these, Next.js fills X-Forwarded-For from the connection itself.
  for (const name of CLIENT_IP_HEADERS) headers.delete(name);
  const secret = process.env.TWOOFUS_PROXY_SECRET;
  if (secret) headers.set(PROXY_AUTH_HEADER, secret);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: [
    "/api/:path*",
    {
      // Pages only: not build assets, icons, the service worker or static files.
      source:
        "/((?!api/|_next/static|_next/image|favicon.ico|icon.svg|apple-icon.png|icons/|brand/|demo/|offline.html|sw.js|manifest.webmanifest).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
