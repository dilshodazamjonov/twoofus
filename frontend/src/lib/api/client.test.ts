import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeApi } from "@/test/api";

import { ApiError, apiRequest, onUnauthenticated, readCsrfCookie } from "./client";

afterEach(() => onUnauthenticated(null));

describe("apiRequest", () => {
  it("sends reads same-origin, uncached and without a CSRF header", async () => {
    const { fetchMock, calls } = fakeApi({ "GET /api/v1/room": { body: { ok: true } } });
    await expect(apiRequest("/api/v1/room")).resolves.toEqual({ ok: true });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
    expect(init.cache).toBe("no-store");
    expect(calls[0].headers.get("X-CSRF-Token")).toBeNull();
  });

  it("echoes the CSRF cookie on writes", async () => {
    const { calls } = fakeApi({ "POST /api/v1/room/tulips": { status: 201, body: { id: "1" } } });
    await apiRequest("/api/v1/room/tulips", { method: "POST", body: { note: "x" } });
    expect(calls[0].headers.get("X-CSRF-Token")).toBe("test-csrf-token");
    expect(calls[0].headers.get("Content-Type")).toBe("application/json");
    expect(calls[0].body).toEqual({ note: "x" });
  });

  it("fetches a CSRF token first when there is no cookie", async () => {
    const { calls } = fakeApi({
      "GET /api/v1/auth/csrf": () => {
        document.cookie = "twoofus_csrf=fresh-token; path=/";
        return { body: { csrf_token: "fresh-token" } };
      },
      "POST /api/v1/auth/logout": { body: { authenticated: false, csrf_token: "x" } },
    });
    document.cookie = "twoofus_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    await apiRequest("/api/v1/auth/logout", { method: "POST" });
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["GET /api/v1/auth/csrf", "POST /api/v1/auth/logout"]);
    expect(calls[1].headers.get("X-CSRF-Token")).toBe("fresh-token");
  });

  it("refreshes the token once after csrf_failed", async () => {
    let attempts = 0;
    const { calls } = fakeApi({
      "GET /api/v1/auth/csrf": () => {
        document.cookie = "twoofus_csrf=second; path=/";
        return { body: { csrf_token: "second" } };
      },
      "PUT /api/v1/me/sharing": () => {
        attempts += 1;
        return attempts === 1
          ? { status: 403, body: { error: { code: "csrf_failed", message: "Security check failed." } } }
          : { body: { share_now_playing: false } };
      },
    });
    await expect(apiRequest("/api/v1/me/sharing", { method: "PUT", body: {} })).resolves.toEqual({
      share_now_playing: false,
    });
    expect(calls.at(-1)?.headers.get("X-CSRF-Token")).toBe("second");
    expect(attempts).toBe(2);
  });

  it("turns error bodies into ApiError with code, message and Retry-After", async () => {
    fakeApi({
      "POST /api/v1/room/tulips": {
        status: 429,
        body: { error: { code: "rate_limited", message: "Too many attempts." } },
        headers: { "Retry-After": "42" },
      },
    });
    const error = await apiRequest("/api/v1/room/tulips", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 429, code: "rate_limited", message: "Too many attempts.", retryAfterSeconds: 42 });
  });

  it("reports a lost session, but not a wrong password", async () => {
    const handler = vi.fn();
    onUnauthenticated(handler);
    fakeApi({
      "GET /api/v1/room": { status: 401, body: { error: { code: "session_expired", message: "Expired." } } },
      "POST /api/v1/auth/login": { status: 401, body: { error: { code: "invalid_credentials", message: "Wrong." } } },
    });
    await expect(apiRequest("/api/v1/auth/login", { method: "POST", body: {} })).rejects.toMatchObject({
      code: "invalid_credentials",
    });
    expect(handler).not.toHaveBeenCalled();
    await expect(apiRequest("/api/v1/room")).rejects.toMatchObject({ code: "session_expired" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("maps network failures to a friendly error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(apiRequest("/api/v1/room")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});

describe("readCsrfCookie", () => {
  it("prefers the __Host- cookie name used on HTTPS", () => {
    expect(readCsrfCookie("a=1; __Host-twoofus_csrf=secure%20value; b=2")).toBe("secure value");
    expect(readCsrfCookie("twoofus_csrf=dev")).toBe("dev");
    expect(readCsrfCookie("other=1")).toBeNull();
  });
});
