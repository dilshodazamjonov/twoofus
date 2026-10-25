"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { sessionResource } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";

/** Public pages send signed-in visitors straight to their room. */
export function RedirectIfSignedIn({ to = "/room" }: { to?: string }) {
  const session = useResource(sessionResource);
  const router = useRouter();
  const authenticated = session.data?.authenticated === true;
  useEffect(() => {
    if (authenticated) router.replace(to);
  }, [authenticated, router, to]);
  return null;
}
