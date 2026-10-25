// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { proxy } from "./proxy";

const ORIGIN = "http://127.0.0.1:3000";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("proxy", () => {
  it("sends visitors without a session cookie to sign-in", () => {
    const response = proxy(new NextRequest(`${ORIGIN}/settings`));
    expect(response.status).toBe(307);
    // Next.js turns same-origin redirects into relative ones before sending
    // them, so the browser stays on the host it used (checked in the e2e run).
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.pathname + location.search).toBe("/sign-in?next=%2Fsettings");
  });

  it("gives every page its own CSP nonce, and passes it to the renderer", () => {
    const first = proxy(new NextRequest(`${ORIGIN}/room`, { headers: { cookie: "twoofus_session=x" } }));
    const second = proxy(new NextRequest(`${ORIGIN}/room`, { headers: { cookie: "twoofus_session=x" } }));
    const policy = first.headers.get("content-security-policy") ?? "";
    expect(policy).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
    expect(policy).not.toBe(second.headers.get("content-security-policy"));
    // Next.js reads the nonce from the (rewritten) request header.
    expect(first.headers.get("x-middleware-request-content-security-policy")).toBe(policy);
  });

  it("adds the proxy secret to API requests and drops any client-supplied one", () => {
    vi.stubEnv("TWOOFUS_PROXY_SECRET", "server-side-secret-value-0123456789");
    const forged = new NextRequest(`${ORIGIN}/api/v1/config`, {
      headers: { "x-twoofus-proxy-auth": "guess" },
    });
    const response = proxy(forged);
    expect(response.headers.get("x-middleware-request-x-twoofus-proxy-auth")).toBe(
      "server-side-secret-value-0123456789",
    );
    expect(response.headers.get("content-security-policy")).toBeNull();
  });

  it("never lets the browser choose the client IP the API sees", () => {
    const spoofed = new NextRequest(`${ORIGIN}/api/v1/auth/login`, {
      method: "POST",
      headers: { "x-forwarded-for": "203.0.113.7", "x-real-ip": "203.0.113.7", forwarded: "for=203.0.113.7" },
    });
    const kept = (proxy(spoofed).headers.get("x-middleware-override-headers") ?? "").split(",");
    expect(kept).not.toContain("x-forwarded-for");
    expect(kept).not.toContain("x-real-ip");
    expect(kept).not.toContain("forwarded");
  });

  it("forwards API requests without the header when no secret is configured (local dev)", () => {
    vi.stubEnv("TWOOFUS_PROXY_SECRET", "");
    const forged = new NextRequest(`${ORIGIN}/api/v1/config`, {
      headers: { "x-twoofus-proxy-auth": "guess" },
    });
    const response = proxy(forged);
    expect(response.headers.get("x-middleware-request-x-twoofus-proxy-auth")).toBeNull();
    expect(response.headers.get("x-middleware-override-headers")).not.toContain("x-twoofus-proxy-auth");
  });
});
