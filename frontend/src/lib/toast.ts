// Small notifications ("Tulip sent", "Copied"). Rendered by <Toaster/>.
import { useSyncExternalStore } from "react";

export type ToastTone = "info" | "success" | "error" | "tulip";
export type Toast = { id: number; message: string; tone: ToastTone };

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

export function dismissToast(id: number): void {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function toast(message: string, tone: ToastTone = "info", durationMs = 4_500): number {
  const id = nextId++;
  toasts = [...toasts.slice(-2), { id, message, tone }]; // at most three at a time
  emit();
  if (typeof window !== "undefined") window.setTimeout(() => dismissToast(id), durationMs);
  return id;
}

const EMPTY: Toast[] = [];

export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => toasts,
    () => EMPTY,
  );
}
