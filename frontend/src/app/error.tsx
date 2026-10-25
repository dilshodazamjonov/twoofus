"use client";

import { RefreshCw } from "lucide-react";

import { LogoMark } from "@/components/brand/logo-mark";
import { Button } from "@/components/ui/button";

export default function ErrorPage({ retry }: { error: unknown; retry: () => void }) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
      <LogoMark className="size-16" />
      <h1 className="font-display text-4xl font-semibold">Something went wrong</h1>
      <Button onClick={retry} icon={<RefreshCw aria-hidden className="size-4" />} className="mt-2">
        Try again
      </Button>
    </main>
  );
}
