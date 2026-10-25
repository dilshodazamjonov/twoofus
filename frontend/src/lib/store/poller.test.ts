import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";

import { backoffDelay, createPoller } from "./poller";

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("createPoller", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0); // no jitter
    setVisibility("visible");
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shares one request between subscribers and polls at the interval", async () => {
    const fetcher = vi.fn().mockResolvedValue({ n: 1 });
    const poller = createPoller({ fetcher, interval: () => 20_000 });
    const stopA = poller.subscribe(() => undefined);
    const stopB = poller.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(poller.getSnapshot().data).toEqual({ n: 1 });
    await vi.advanceTimersByTimeAsync(19_999);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
    stopA();
    stopB();
  });

  it("sends nothing while hidden and refreshes when visible again", async () => {
    const fetcher = vi.fn().mockResolvedValue({});
    const poller = createPoller({ fetcher, interval: () => 20_000 });
    const stop = poller.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    setVisibility("hidden");
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(poller.getSnapshot().paused).toBe(true);
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);
    stop();
  });

  it("honours Retry-After and backs off on errors", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(429, "rate_limited", "slow down", 30))
      .mockRejectedValueOnce(new ApiError(503, "service_unavailable", "down"))
      .mockResolvedValue({ ok: true });
    const poller = createPoller({ fetcher, interval: () => 20_000 });
    const stop = poller.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(poller.getSnapshot().error?.code).toBe("rate_limited");
    await vi.advanceTimersByTimeAsync(29_999);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetcher).toHaveBeenCalledTimes(2); // after Retry-After
    await vi.advanceTimersByTimeAsync(10_000); // second failure: 2nd step of the backoff
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(poller.getSnapshot().error).toBeUndefined();
    stop();
  });

  it("stops polling when the session is gone", async () => {
    const fetcher = vi.fn().mockRejectedValue(new ApiError(401, "session_expired", "expired"));
    const poller = createPoller({ fetcher, interval: () => 20_000 });
    const stop = poller.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(300_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    stop();
  });

  it("aborts the request and stops when the last subscriber leaves", async () => {
    let signal: AbortSignal | undefined;
    const fetcher = vi.fn((s: AbortSignal) => {
      signal = s;
      return new Promise(() => undefined); // never resolves
    });
    const poller = createPoller({ fetcher, interval: () => 20_000 });
    const stop = poller.subscribe(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(signal?.aborted).toBe(false);
    stop();
    expect(signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("backoffDelay", () => {
  it("grows exponentially up to a minute", () => {
    const error = new ApiError(503, "service_unavailable", "down");
    expect([1, 2, 3, 4, 5, 9].map((n) => backoffDelay(error, n))).toEqual([5_000, 10_000, 20_000, 40_000, 60_000, 60_000]);
  });

  it("uses Retry-After within sane bounds", () => {
    expect(backoffDelay(new ApiError(429, "x", "x", 1), 1)).toBe(5_000);
    expect(backoffDelay(new ApiError(429, "x", "x", 3_600), 1)).toBe(300_000);
  });
});
