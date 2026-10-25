// A tiny shared-data store for one-shot API resources (config, room, ...).
// Every component that uses the same resource shares one request and one
// result; useSyncExternalStore keeps React in sync without effects that set
// state, and the server snapshot is always "idle" so hydration never differs.
import { useEffect, useSyncExternalStore } from "react";

import { ApiError } from "@/lib/api/client";

export type ResourceStatus = "idle" | "loading" | "ready" | "error";

export type ResourceState<T> = {
  data: T | undefined;
  error: ApiError | undefined;
  /** "ready" once data exists, even while a refresh is running. */
  status: ResourceStatus;
  refreshing: boolean;
  /** Client time (ms) of the last successful response. */
  updatedAt: number | null;
};

export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError(0, "unexpected", "Something unexpected happened. Please try again.");
}

export type Resource<T> = {
  load: () => Promise<T | undefined>;
  mutate: (data: T) => void;
  reset: () => void;
  getSnapshot: () => ResourceState<T>;
  getServerSnapshot: () => ResourceState<T>;
  subscribe: (listener: () => void) => () => void;
};

export function createResource<T>(fetcher: (signal: AbortSignal) => Promise<T>): Resource<T> {
  const initial: ResourceState<T> = {
    data: undefined,
    error: undefined,
    status: "idle",
    refreshing: false,
    updatedAt: null,
  };
  let state = initial;
  let inflight: Promise<T | undefined> | null = null;
  let controller: AbortController | null = null;
  let generation = 0;
  const listeners = new Set<() => void>();

  const emit = () => listeners.forEach((listener) => listener());
  const set = (next: Partial<ResourceState<T>>) => {
    state = { ...state, ...next };
    emit();
  };

  function load(): Promise<T | undefined> {
    if (inflight) return inflight;
    const myGeneration = generation;
    controller = new AbortController();
    set({ status: state.data === undefined ? "loading" : state.status, refreshing: true });
    inflight = fetcher(controller.signal)
      .then(
        (data) => {
          if (myGeneration === generation) {
            set({ data, error: undefined, status: "ready", refreshing: false, updatedAt: Date.now() });
          }
          return data;
        },
        (error: unknown) => {
          if (myGeneration === generation) {
            set({
              error: asApiError(error),
              status: state.data === undefined ? "error" : "ready",
              refreshing: false,
            });
          }
          return undefined;
        },
      )
      .finally(() => {
        if (myGeneration === generation) inflight = null;
      });
    return inflight;
  }

  function mutate(data: T): void {
    set({ data, error: undefined, status: "ready", updatedAt: Date.now() });
  }

  function reset(): void {
    generation += 1;
    controller?.abort();
    controller = null;
    inflight = null;
    state = initial;
    emit();
  }

  const subscribe = (listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  };
  const getSnapshot = () => state;
  const getServerSnapshot = () => initial;

  return { load, mutate, reset, getSnapshot, getServerSnapshot, subscribe };
}

/** Subscribe to a resource and load it once (when enabled and nothing is loaded yet). */
export function useResource<T>(
  resource: Resource<T>,
  { enabled = true }: { enabled?: boolean } = {},
): ResourceState<T> {
  const snapshot = useSyncExternalStore(
    resource.subscribe,
    resource.getSnapshot,
    resource.getServerSnapshot,
  );
  useEffect(() => {
    if (enabled && resource.getSnapshot().status === "idle") void resource.load();
  }, [enabled, resource, snapshot.status]);
  return snapshot;
}
