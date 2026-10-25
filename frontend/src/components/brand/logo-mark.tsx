import { cn } from "@/components/ui/cn";

/** The app's mark: a tulip (the app icon is the same drawing, assets/app-icon.svg). */
export function LogoMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("shrink-0", className)}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <path d="M12 13.5V22" stroke="var(--sage-ink)" />
      <path d="M12 22c0-3 2.2-5.2 5.5-5.2 0 3-2.4 5.2-5.5 5.2Z" stroke="var(--sage-ink)" fill="var(--sage)" />
      <path d="M12 19.5c-.6-2.1-2.2-3.4-4.5-3.6" stroke="var(--sage-ink)" />
      <path
        d="M12 13.5c2.8 0 5-2.2 5-5V3.5l-2.6 2.2L12 2.5 9.6 5.7 7 3.5v5c0 2.8 2.2 5 5 5Z"
        stroke="var(--accent)"
        fill="var(--accent)"
      />
    </svg>
  );
}
