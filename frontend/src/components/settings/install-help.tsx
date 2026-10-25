"use client";

import { CheckCircle2, Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useInstallPrompt, usePlatform } from "@/lib/platform";

/** Add-to-Home-Screen help. Safari has no install prompt; Chromium browsers get a real install button. */
export function InstallHelp({ appName }: { appName: string }) {
  const platform = usePlatform();
  const install = useInstallPrompt();

  if (platform?.standalone) {
    return (
      <p className="flex items-center gap-2 text-[0.97rem]">
        <CheckCircle2 aria-hidden className="size-5 text-sage-ink" />
        Installed.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {install ? (
        <Button onClick={() => void install()} icon={<Download aria-hidden className="size-4" />}>
          Install {appName}
        </Button>
      ) : null}
      <p className="text-[0.95rem]">
        iPhone: in Safari, tap <strong>Share</strong>, then <strong>Add to Home Screen</strong>.
      </p>
    </div>
  );
}
