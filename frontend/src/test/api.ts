// A tiny fake of the backend for component tests: route by "METHOD /path".
import { vi } from "vitest";

type Reply = { status?: number; body?: unknown; headers?: Record<string, string> };
type Handler = (request: { method: string; path: string; body: unknown; headers: Headers }) => Reply | Promise<Reply>;

export function fakeApi(routes: Record<string, Handler | Reply>) {
  const calls: Array<{ method: string; path: string; body: unknown; headers: Headers }> = [];
  document.cookie = "twoofus_csrf=test-csrf-token; path=/";
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(typeof input === "string" ? input : input.toString(), "http://127.0.0.1:3000");
    const method = (init.method ?? "GET").toUpperCase();
    const request = {
      method,
      path: url.pathname,
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
      headers: new Headers(init.headers),
    };
    calls.push(request);
    const route = routes[`${method} ${url.pathname}`];
    if (!route) return new Response(JSON.stringify({ error: { code: "not_found", message: "Not found." } }), { status: 404 });
    const reply = typeof route === "function" ? await route(request) : route;
    const status = reply.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(reply.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json", ...(reply.headers ?? {}) },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}
