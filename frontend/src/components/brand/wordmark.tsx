import { cn } from "@/components/ui/cn";

import { LogoMark } from "./logo-mark";

export function Wordmark({ name, className }: { name: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark className="size-9" />
      <span className="font-display text-[1.45rem] font-semibold leading-none tracking-[0.01em] text-ink">{name}</span>
    </span>
  );
}
