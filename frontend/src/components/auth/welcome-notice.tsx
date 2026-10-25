"use client";

import { useSearchParams } from "next/navigation";

import { Alert } from "@/components/ui/alert";

export function WelcomeNotice() {
  const params = useSearchParams();
  if (params.get("deleted") === "1") {
    return (
      <Alert tone="info" className="mt-8" title="Your account was deleted" />
    );
  }
  return null;
}
