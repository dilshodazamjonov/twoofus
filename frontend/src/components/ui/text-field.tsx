import { useId, type ComponentProps } from "react";

import { cn } from "./cn";

type TextFieldProps = Omit<ComponentProps<"input">, "id"> & {
  label: string;
  hint?: string;
  error?: string | null;
};

export function TextField({ label, hint, error, className, ...props }: TextFieldProps) {
  const id = useId();
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(
          "block min-h-12 w-full rounded-2xl border bg-surface px-4 text-base text-ink placeholder:text-muted/70",
          "transition-colors focus:border-accent focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-2",
          error ? "border-danger" : "border-line-strong/70",
        )}
        {...props}
      />
      {hint ? (
        <p id={`${id}-hint`} className="text-sm text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="text-sm font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
