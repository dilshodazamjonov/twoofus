"use client";

import { useId } from "react";

import { cn } from "./cn";

type SwitchProps = {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  busy?: boolean;
  className?: string;
};

/** An accessible on/off switch (role="switch") with a 44 px touch target. */
export function Switch({ checked, onChange, label, description, disabled, busy, className }: SwitchProps) {
  const id = useId();
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className="min-w-0 pt-2.5">
        <p id={`${id}-label`} className="font-medium text-ink">
          {label}
        </p>
        {description ? (
          <p id={`${id}-description`} className="mt-0.5 text-sm text-muted">
            {description}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={description ? `${id}-description` : undefined}
        aria-busy={busy || undefined}
        disabled={disabled || busy}
        onClick={() => onChange(!checked)}
        className="group -m-1 inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-full p-1 disabled:opacity-55"
      >
        <span
          className={cn(
            "relative inline-flex h-8 w-[3.25rem] items-center rounded-full border transition-colors duration-200",
            checked ? "border-accent bg-accent" : "border-line-strong bg-surface-2",
          )}
        >
          <span
            className={cn(
              "absolute left-[3px] size-[1.375rem] rounded-full shadow-sm transition-transform duration-200",
              checked ? "translate-x-[1.25rem] bg-accent-ink" : "translate-x-0 bg-line-strong",
            )}
          />
        </span>
      </button>
    </div>
  );
}
