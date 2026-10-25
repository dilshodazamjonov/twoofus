import { CircleAlert, Info, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "./cn";

type Tone = "info" | "warning" | "error" | "success";

const tones: Record<Tone, string> = {
  info: "border-line bg-surface-2 text-ink",
  warning: "border-transparent bg-warning-soft text-warning-ink",
  error: "border-transparent bg-danger-soft text-ink",
  success: "border-transparent bg-sage-soft text-sage-ink",
};

const icons: Record<Tone, ReactNode> = {
  info: <Info aria-hidden className="mt-0.5 size-5 shrink-0 text-muted" />,
  warning: <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />,
  error: <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0 text-danger" />,
  success: <Sparkles aria-hidden className="mt-0.5 size-5 shrink-0" />,
};

export function Alert({
  tone = "info",
  title,
  children,
  className,
  action,
}: {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn("flex gap-3 rounded-2xl border px-4 py-3 text-[0.95rem]", tones[tone], className)}
    >
      {icons[tone]}
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className={cn(title && "mt-0.5", "text-[0.93rem] opacity-95")}>{children}</div> : null}
        {action ? <div className="mt-2">{action}</div> : null}
      </div>
    </div>
  );
}
