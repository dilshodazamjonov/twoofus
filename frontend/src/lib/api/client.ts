// The one place that talks HTTP. Every request goes to the same-origin /api
// proxy (Next.js rewrites it to FastAPI), so cookies stay first-party and no
// credential ever appears in JavaScript, URLs, storage or logs:
//
// * The session cookie is HttpOnly; the browser attaches it.
// * State-changing requests echo the CSRF cookie in X-CSRF-Token
//   (signed double-submit). It is read from the cookie at
//   request time, so several tabs never disagree about the current token.
// * Errors become ApiError with the backend's stable `code`.

import { noteRequestOutcome } from "@/lib/connectivity";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** Seconds from a Retry-After header (429/503), if any. */
  readonly retryAfterSeconds: number | null;

  constructor(status: number, code: string, message: string, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  /** The session is gone (expired, revoked, signed out elsewhere). */
  get isUnauthenticated(): boolean {
    return this.status === 401 && (this.code === "not_authenticated" || this.code === "session_expired");
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

const CSRF_COOKIES = ["__Host-twoofus_csrf", "twoofus_csrf"];
const DEFAULT_TIMEOUT_MS = 15_000;

let unauthenticatedHandler: ((error: ApiError) => void) | null = null;

/** Called once by the session store: any 401 from a signed-in call ends the session. */
export function onUnauthenticated(handler: ((error: ApiError) => void) | null): void {
  unauthenticatedHandler = handler;
}

export function readCsrfCookie(cookieString: string = typeof document === "undefined" ? "" : document.cookie): string | null {
  for (const part of cookieString.split(";")) {
    const index = part.indexOf("=");
    if (index < 0) continue;
    const name = part.slice(0, index).trim();
    if (CSRF_COOKIES.includes(name)) {
      const value = part.slice(index + 1).trim();
      if (value) return decodeURIComponent(value);
    }
  }
  return null;
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.ceil(seconds);
  const date = Date.parse(value);
  return Number.isNaN(date) ? null : Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = "Something went wrong. Please try again.";
  try {
    const body = (await response.json()) as { error?: { code?: unknown; message?: unknown } };
    if (typeof body.error?.code === "string") code = body.error.code;
    if (typeof body.error?.message === "string") message = body.error.message;
  } catch {
    // Not JSON (e.g. the proxy could not reach the backend): keep the defaults.
    if (response.status >= 500) {
      code = response.status === 502 || response.status === 504 ? "backend_unreachable" : code;
      message = "The server is not responding right now.";
    }
  }
  return new ApiError(response.status, code, message, parseRetryAfter(response.headers.get("Retry-After")));
}

type RequestOptions = {
  method?: HttpMethod;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
};

async function send(path: string, options: RequestOptions, csrfToken: string | null): Promise<Response> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;

  const controller = new AbortController();
  const onAbort = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", onAbort, { once: true });
  if (options.signal?.aborted) controller.abort(options.signal.reason);
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
    noteRequestOutcome(true);
    return response;
  } catch (error) {
    if (options.signal?.aborted) throw error; // the caller cancelled: not an API failure
    if (timedOut) throw new ApiError(0, "timeout", "The server took too long to answer.");
    noteRequestOutcome(false);
    throw new ApiError(0, "network_error", "You seem to be offline, or the server is unreachable.");
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", onAbort);
  }
}

async function freshCsrfToken(signal?: AbortSignal): Promise<string | null> {
  const response = await send("/api/v1/auth/csrf", { signal }, null);
  if (!response.ok) throw await toApiError(response);
  const body = (await response.json()) as { csrf_token?: string };
  // Prefer the cookie: it is what the server compares against.
  return readCsrfCookie() ?? body.csrf_token ?? null;
}

/**
 * Call the backend. `path` always starts with /api/v1/. Resolves with the
 * parsed JSON (or undefined for 204), rejects with ApiError.
 */
export async function apiRequest<T>(path: `/api/v1/${string}`, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const mutating = method !== "GET";
  let csrf = mutating ? (readCsrfCookie() ?? (await freshCsrfToken(options.signal))) : null;

  let response = await send(path, options, csrf);
  if (mutating && response.status === 403) {
    const error = await toApiError(response.clone());
    if (error.code === "csrf_failed") {
      // The token belongs to an older session (e.g. signed in in another tab): refresh once.
      csrf = await freshCsrfToken(options.signal);
      response = await send(path, options, csrf);
    }
  }
  if (!response.ok) {
    const error = await toApiError(response);
    if (error.isUnauthenticated) unauthenticatedHandler?.(error);
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
