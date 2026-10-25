"use client";

import { DEFAULT_APP_NAME } from "@/lib/app-name";
import { configResource } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";

/** The configured app name (backend APP_NAME), with the build default until it loads. */
export function AppName() {
  const config = useResource(configResource);
  return <>{config.data?.app_name ?? DEFAULT_APP_NAME}</>;
}
