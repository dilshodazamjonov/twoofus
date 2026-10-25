"use client";

import { RefreshCw, WifiOff } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { DEFAULT_APP_NAME } from "@/lib/app-name";
import { useOffline } from "@/lib/connectivity";
import { captureInstallPrompt } from "@/lib/platform";
import { applyUpdate, registerServiceWorker, useUpdateAvailable } from "@/lib/pwa/service-worker";
import { configResource } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";

/** App-wide PWA behaviour: service worker, install prompt, update + offline notices. */
export function PwaRuntime() {
  const offline = useOffline();
  const updateAvailable = useUpdateAvailable();
  const config = useResource(configResource);
  const pathname = usePathname();
  const appName = config.data?.app_name;

  useEffect(() => {
    registerServiceWorker();
    return captureInstallPrompt();
  }, []);

  // The HTML title is rendered with the build-time default name; follow the
  // backend's APP_NAME when it has been changed.
  useEffect(() => {
    if (!appName || appName === DEFAULT_APP_NAME) return;
    document.title = document.title.replaceAll(DEFAULT_APP_NAME, appName);
    document.querySelector('meta[name="apple-mobile-web-app-title"]')?.setAttribute("content", appName);
  }, [appName, pathname]);

  return (
    <>
      {offline ? (
        <div
          role="status"
          className="fixed inset-x-0 top-[calc(env(safe-area-inset-top)+0.5rem)] z-50 mx-auto flex w-fit max-w-[calc(100vw-2rem)] items-center gap-2 rounded-full border border-line bg-surface px-4 py-2 text-sm text-ink shadow-card"
        >
          <WifiOff aria-hidden className="size-4 shrink-0 text-muted" />
          You&apos;re offline.
        </div>
      ) : null}
      {updateAvailable ? (
        <div
          role="status"
          className="fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)+5.75rem)] z-50 mx-auto flex w-[min(calc(100vw-2rem),26rem)] items-center gap-3 rounded-2xl border border-line bg-surface p-3 pl-4 text-[0.95rem] shadow-card md:bottom-6"
        >
          <p className="min-w-0 flex-1">A new version is ready.</p>
          <Button size="sm" onClick={applyUpdate} icon={<RefreshCw aria-hidden className="size-4" />}>
            Refresh
          </Button>
        </div>
      ) : null}
    </>
  );
}
