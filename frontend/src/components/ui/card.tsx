import type { ComponentProps } from "react";

import { cn } from "./cn";

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn("rounded-[1.75rem] border border-line bg-surface p-5 shadow-card sm:p-6", className)}
      {...props}
    />
  );
}

export function CardTitle({ className, ...props }: ComponentProps<"h2">) {
  return <h2 className={cn("font-display text-[1.65rem] font-semibold leading-tight text-ink", className)} {...props} />;
}

export function CardDescription({ className, ...props }: ComponentProps<"p">) {
  return <p className={cn("mt-1 text-[0.95rem] text-muted", className)} {...props} />;
}
