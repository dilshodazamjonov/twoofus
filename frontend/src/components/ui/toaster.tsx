"use client";

import { X } from "lucide-react";

import { TulipIcon } from "@/components/brand/tulip-icon";

import { dismissToast, useToasts } from "@/lib/toast";

import { cn } from "./cn";

export function Toaster() {
  const toasts = useToasts();
  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+5.75rem)] z-50 flex flex-col items-center gap-2 px-4 md:bottom-8"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.tone === "error" ? "alert" : "status"}
          className={cn(
            "pointer-events-auto flex w-full max-w-sm animate-fade-up items-center gap-3 rounded-2xl border py-2 pl-4 pr-1 text-[0.95rem] shadow-card",
            t.tone === "error" ? "border-transparent bg-danger-soft text-ink" : "border-line bg-surface text-ink",
          )}
        >
          {t.tone === "tulip" ? <TulipIcon className="size-5 shrink-0 text-accent" /> : null}
          <p className="min-w-0 flex-1 py-1.5">{t.message}</p>
          <button
            type="button"
            onClick={() => dismissToast(t.id)}
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-full text-muted hover:bg-surface-2"
            aria-label="Dismiss notification"
          >
            <X aria-hidden className="size-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
