"use client";

import { useEffect, useState } from "react";

type Check = { label: string; value: string; ok: boolean };

type ConfigResponse = {
  app_name: string;
  demo_mode: boolean;
  providers: Record<string, { available: boolean; experimental: boolean }>;
};

async function getJson<T>(path: string): Promise<{ status: number; body: T | null }> {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store" });
  const body = (await response.json().catch(() => null)) as T | null;
  return { status: response.status, body };
}

export function FoundationStatus() {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [connectResult, setConnectResult] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Set when the backend redirects here after a Spotify authorisation.
      const params = new URLSearchParams(window.location.search);
      const connect = params.get("connect")
        ? `${params.get("connect")}: ${params.get("result") ?? "unknown"}`
        : null;
      const results: Check[] = [];
      try {
        const health = await getJson<{ status: string }>("/api/v1/health");
        results.push({ label: "API via same-origin proxy", value: health.body?.status ?? `HTTP ${health.status}`, ok: health.status === 200 });
        const ready = await getJson<{ database: string; migrations: string }>("/api/v1/ready");
        results.push({
          label: "Database / migrations",
          value: ready.body ? `${ready.body.database} / ${ready.body.migrations}` : `HTTP ${ready.status}`,
          ok: ready.status === 200,
        });
        const config = await getJson<ConfigResponse>("/api/v1/config");
        if (config.body) {
          for (const [name, provider] of Object.entries(config.body.providers)) {
            results.push({
              label: `Provider: ${name}${provider.experimental ? " (experimental)" : ""}`,
              value: provider.available ? "enabled" : "not configured",
              ok: provider.available,
            });
          }
        }
      } catch {
        results.push({ label: "API via same-origin proxy", value: "unreachable", ok: false });
      }
      if (!cancelled) {
        setConnectResult(connect);
        setChecks(results);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section aria-live="polite" className="rounded-2xl border border-stone-200 bg-white/70 p-5 dark:border-stone-800 dark:bg-stone-900/60">
      {connectResult && (
        <p className="mb-4 rounded-lg bg-stone-100 px-3 py-2 text-sm text-stone-700 dark:bg-stone-800 dark:text-stone-200">
          Last connection attempt — {connectResult}
        </p>
      )}
      {checks === null ? (
        <p className="text-sm text-stone-500">Checking the backend…</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {checks.map((check) => (
            <li key={check.label} className="flex items-center justify-between gap-4">
              <span className="text-stone-700 dark:text-stone-300">{check.label}</span>
              <span className={check.ok ? "text-emerald-700 dark:text-emerald-400" : "text-stone-500"}>{check.value}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
