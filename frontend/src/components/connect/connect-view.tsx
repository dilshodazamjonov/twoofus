"use client";

import { FlaskConical, Music2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { SpotifyLogo } from "@/components/brand/spotify-logo";
import { SharingSettings } from "@/components/settings/sharing-settings";
import { Alert } from "@/components/ui/alert";
import { Card, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { cn } from "@/components/ui/cn";
import { Skeleton } from "@/components/ui/skeleton";
import type { ProviderName } from "@/lib/api/types";
import { DEMO_UI } from "@/lib/demo-ui";
import { providersResource } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";

import { DEMO_OPTION, DemoConnect } from "@demo-ui";

import { ConnectionStatus } from "./connection-status";
import { SpotifyConnect } from "./spotify-connect";
import { YandexConnect } from "./yandex-connect";

const SPOTIFY_RESULTS: Record<string, { tone: "success" | "info" | "error"; title: string; text: string }> = {
  connected: { tone: "success", title: "Spotify is connected", text: "" },
  access_denied: { tone: "info", title: "Spotify wasn't connected", text: "" },
  session_mismatch: { tone: "error", title: "Please try again here", text: "Spotify sent you back to a different browser." },
  invalid_state: { tone: "error", title: "That link expired", text: "Please start again." },
  failed: { tone: "error", title: "Spotify didn't confirm", text: "Please try again." },
};

export function ConnectView() {
  const providers = useResource(providersResource);
  const params = useSearchParams();
  const router = useRouter();
  const [chosen, setChosen] = useState<ProviderName | null>(null);
  const [switching, setSwitching] = useState(false);

  const spotifyResult = params.get("connect") === "spotify" ? params.get("result") : null;
  const result = spotifyResult ? SPOTIFY_RESULTS[spotifyResult] ?? SPOTIFY_RESULTS.failed : null;

  // Coming back from Spotify: reload the connection, and keep the banner but drop the query.
  useEffect(() => {
    if (!spotifyResult) return;
    void providersResource.load();
  }, [spotifyResult]);

  // The connection may complete elsewhere (Spotify tab, another device): refresh when we're visible again.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void providersResource.load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  const connection = providers.data?.connection ?? null;
  const pending = providers.data?.pending_authorization ?? null;
  // Production builds have no demo UI at all, whatever the server says.
  const available = (providers.data?.providers ?? []).filter((p) => p.name !== "demo" || DEMO_UI);
  const showPicker = !connection || switching;
  const selected: ProviderName | null =
    chosen ?? (pending?.provider === "yandex" ? "yandex" : connection && switching ? connection.provider : null);

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-display text-[2.5rem] font-semibold leading-[1.05] sm:text-5xl">Connect your music</h1>
      </header>

      {result ? (
        <Alert tone={result.tone} title={result.title} action={null}>
          {result.text}{" "}
          <button
            type="button"
            className="font-medium underline underline-offset-4"
            onClick={() => router.replace("/connect")}
          >
            Dismiss
          </button>
        </Alert>
      ) : null}

      <Card aria-labelledby="service-heading">
        <CardTitle id="service-heading">Music service</CardTitle>
        <div className="mt-5">
          {providers.status === "loading" || providers.status === "idle" ? (
            <Skeleton className="h-28" />
          ) : providers.status === "error" && !providers.data ? (
            <Alert tone="error">{providers.error?.message ?? "Couldn't load your music services."}</Alert>
          ) : connection && !switching ? (
            <ConnectionStatus connection={connection} onReconnect={() => setSwitching(true)} />
          ) : null}

          {providers.data && showPicker ? (
            <fieldset className="space-y-3">
              <legend className="sr-only">Choose a music service</legend>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {available.map((p) => (
                  <ProviderOption
                    key={p.name}
                    name={p.name}
                    label={p.label}
                    available={p.available}
                    experimental={p.experimental}
                    selected={selected === p.name}
                    onSelect={() => setChosen(p.name)}
                  />
                ))}
              </div>
              {switching ? (
                <button
                  type="button"
                  className="min-h-11 text-sm font-medium text-accent-text underline-offset-4 hover:underline"
                  onClick={() => {
                    setSwitching(false);
                    setChosen(null);
                  }}
                >
                  Keep my current connection
                </button>
              ) : null}
            </fieldset>
          ) : null}

          {showPicker && selected ? (
            <div className="mt-6 border-t border-line pt-6">
              {selected === "spotify" ? <SpotifyConnect reconnect={connection?.provider === "spotify"} /> : null}
              {selected === "yandex" ? <YandexConnect resume={pending?.provider === "yandex"} /> : null}
              {DEMO_UI && selected === "demo" ? <DemoConnect /> : null}
            </div>
          ) : null}
        </div>
      </Card>

      <Card aria-labelledby="sharing-heading">
        <CardTitle id="sharing-heading">Sharing</CardTitle>
        <div className="mt-5">
          <SharingSettings />
        </div>
      </Card>

    </div>
  );
}

function ProviderOption({
  name,
  label,
  available,
  experimental,
  selected,
  onSelect,
}: {
  name: ProviderName;
  label: string;
  available: boolean;
  experimental: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <label
      className={cn(
        "relative flex min-h-24 cursor-pointer flex-col gap-2 rounded-2xl border p-4 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--focus-ring)]",
        selected ? "border-accent bg-accent-soft/40" : "border-line bg-surface hover:bg-surface-2",
        !available && "cursor-not-allowed opacity-60",
      )}
    >
      <input
        type="radio"
        name="provider"
        value={name}
        checked={selected}
        onChange={onSelect}
        disabled={!available}
        className="sr-only"
      />
      <span className="flex items-center justify-between gap-2">
        {name === "spotify" ? (
          <SpotifyLogo width={84} />
        ) : (
          <span className="inline-flex items-center gap-2 font-semibold">
            {name === "yandex" ? <Music2 aria-hidden className="size-4" /> : <FlaskConical aria-hidden className="size-4" />}
            {name === "yandex" ? "Yandex Music" : DEMO_OPTION?.label}
          </span>
        )}
        <span
          aria-hidden="true"
          className={cn(
            "size-5 shrink-0 rounded-full border-2",
            selected ? "border-accent bg-accent shadow-[inset_0_0_0_3px_var(--surface)]" : "border-line-strong",
          )}
        />
      </span>
      <span className="sr-only">{label}</span>
      <span className="text-sm text-muted">
        {!available
          ? "Not set up on this server yet"
          : name === "spotify"
            ? "Official connection"
            : name === "yandex"
              ? "Unofficial, may stop working"
              : DEMO_OPTION?.hint}
      </span>
      {experimental ? <Chip className="w-fit">Experimental</Chip> : null}
      {name === "demo" ? <Chip tone="warning" className="w-fit">Demo</Chip> : null}
    </label>
  );
}
