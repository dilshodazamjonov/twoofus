"use client";

import { CloudOff, RefreshCw } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Wordmark } from "@/components/brand/wordmark";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DEFAULT_APP_NAME } from "@/lib/app-name";
import { configResource, sessionResource, useSessionEnd } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";

import { BottomNav, TopNav } from "./nav";

/**
 * Frame for the signed-in pages. The session is checked here (client side,
 * through the same-origin API) and anonymous visitors are sent to sign-in.
 * The API enforces authentication on every request regardless; this gate only
 * decides what to render.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const session = useResource(sessionResource);
  const config = useResource(configResource);
  const ended = useSessionEnd();
  const router = useRouter();
  const pathname = usePathname();
  const authenticated = session.data?.authenticated === true;
  const anonymous = session.status === "ready" && !authenticated;

  // Expired, revoked or signed out elsewhere: either noticed by an API call in
  // this tab, or reported by the server when the app was opened.
  const expired = ended?.reason === "expired" || session.data?.session_expired === true;
  // Signing out / deleting the account here navigates by itself.
  const leaving = ended?.reason === "signed_out";
  useEffect(() => {
    if (!anonymous || leaving) return;
    const params = new URLSearchParams({ next: pathname });
    if (expired) params.set("expired", "1");
    router.replace(`/sign-in?${params.toString()}`);
  }, [anonymous, expired, leaving, pathname, router]);

  // Opened while offline (or the server was down): try again on our own.
  const unreachable = session.status === "error" && !session.data;
  useEffect(() => {
    if (!unreachable) return;
    const retry = () => void sessionResource.load();
    const timer = window.setInterval(retry, 15_000);
    window.addEventListener("online", retry);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("online", retry);
    };
  }, [unreachable]);

  const appName = config.data?.app_name ?? DEFAULT_APP_NAME;

  if (unreachable) {
    return <Unreachable appName={appName} onRetry={() => void sessionResource.load()} />;
  }
  if (!authenticated) return <ShellSkeleton />;

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded-full bg-accent px-4 py-2 text-accent-ink focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-line/60 bg-bg/90 pt-[env(safe-area-inset-top)] backdrop-blur-sm supports-[not(backdrop-filter:blur(1px))]:bg-bg">
        <div className="mx-auto flex h-16 w-full max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
          <Link href="/room" className="rounded-full" aria-label={`${appName}: home`}>
            <Wordmark name={appName} />
          </Link>
          <TopNav />
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto w-full max-w-5xl flex-1 px-4 pb-[calc(env(safe-area-inset-bottom)+7rem)] pt-6 outline-none sm:px-6 md:pb-16 md:pt-10"
      >
        {children}
      </main>
      <BottomNav />
    </div>
  );
}

function ShellSkeleton() {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 pt-6 sm:px-6" role="status" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-9 w-48" />
      <div className="mt-10 grid gap-6 md:grid-cols-2">
        <Skeleton className="h-80 rounded-[1.75rem]" />
        <Skeleton className="h-80 rounded-[1.75rem]" />
      </div>
    </div>
  );
}

function Unreachable({ appName, onRetry }: { appName: string; onRetry: () => void }) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-5 px-6 text-center">
      <span className="inline-flex size-14 items-center justify-center rounded-full bg-accent-soft text-accent-text">
        <CloudOff aria-hidden className="size-7" />
      </span>
      <h1 className="font-display text-3xl font-semibold">Can&apos;t reach {appName}</h1>
      <Button onClick={onRetry} icon={<RefreshCw aria-hidden className="size-4" />}>
        Try again
      </Button>
    </main>
  );
}
