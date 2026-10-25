import type { ReactNode } from "react";

import { cn } from "./cn";

type Tone = "neutral" | "accent" | "sage" | "warning";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted",
  accent: "bg-accent-soft text-accent-text",
  sage: "bg-sage-soft text-sage-ink",
  warning: "bg-warning-soft text-warning-ink",
};

export function Chip({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-[0.08em]",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
