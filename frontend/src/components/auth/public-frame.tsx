import Link from "next/link";
import type { ReactNode } from "react";

/** Centered, calm frame for the public pages (welcome, sign-in, invitation). */
export function PublicFrame({ children, footer = true }: { children: ReactNode; footer?: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col px-4 pb-[calc(env(safe-area-inset-bottom)+1.5rem)] pt-[calc(env(safe-area-inset-top)+1.5rem)] sm:px-6">
      <main id="main" className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-8">
        {children}
      </main>
      {footer ? (
        <footer className="mx-auto flex w-full max-w-md items-center justify-center text-sm text-muted">
          <Link href="/privacy" className="inline-flex min-h-11 items-center underline-offset-4 hover:underline">
            Privacy
          </Link>
        </footer>
      ) : null}
    </div>
  );
}
