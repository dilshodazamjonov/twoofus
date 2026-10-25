import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { noteRequestOutcome, useOffline } from "./connectivity";

describe("useOffline", () => {
  it("follows what requests actually do, not only navigator.onLine", () => {
    const { result } = renderHook(() => useOffline());
    act(() => noteRequestOutcome(true));
    expect(result.current).toBe(false);

    act(() => noteRequestOutcome(false)); // a request failed at the network level
    expect(result.current).toBe(true);

    act(() => noteRequestOutcome(true)); // the server answered again
    expect(result.current).toBe(false);

    act(() => window.dispatchEvent(new Event("offline")));
    expect(result.current).toBe(true);
    act(() => noteRequestOutcome(true)); // navigator was wrong: the request got through
    expect(result.current).toBe(false);

    act(() => window.dispatchEvent(new Event("offline")));
    act(() => window.dispatchEvent(new Event("online")));
    expect(result.current).toBe(false);
  });
});
