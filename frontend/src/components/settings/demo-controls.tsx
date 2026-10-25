"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { demoApi } from "@/lib/api/demo";
import type { DemoScenario } from "@/lib/api/types";
import { nowPlayingPoller } from "@/lib/resources";
import { toast } from "@/lib/toast";

const LABELS: Record<DemoScenario, string> = {
  live: "Live timeline (plays, pauses, rests)",
  playing: "Playing",
  paused: "Paused",
  idle: "Nothing playing",
  non_music: "Something other than music",
  private_session: "Private session",
  rate_limited: "Rate limited (429)",
  unreachable: "Service unreachable",
  forbidden: "Not allowed (403)",
  reauth_required: "Needs reconnecting",
};

/** Development only: replay any card state through the real backend pipeline. */
export function DemoControls() {
  const [scenario, setScenario] = useState<DemoScenario | null>(null);
  const [available, setAvailable] = useState<DemoScenario[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    demoApi
      .scenario({ signal: controller.signal })
      .then((out) => {
        setScenario(out.scenario);
        setAvailable(out.available);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  async function apply(next: DemoScenario) {
    setBusy(true);
    try {
      const out = await demoApi.setScenario(next);
      setScenario(out.scenario);
      nowPlayingPoller.refresh();
      toast(`Demo scenario: ${LABELS[out.scenario]}.`, "success");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't switch the scenario.", "error");
    } finally {
      setBusy(false);
    }
  }

  if (available.length === 0) return null;
  return (
    <div className="mt-5 rounded-2xl border border-dashed border-line-strong/50 p-4">
      <label htmlFor="demo-scenario" className="text-sm font-semibold">
        Demo scenario
      </label>
      <div className="mt-2 flex flex-wrap gap-2">
        <select
          id="demo-scenario"
          value={scenario ?? "live"}
          onChange={(e) => void apply(e.target.value as DemoScenario)}
          disabled={busy}
          className="min-h-11 w-full min-w-0 flex-1 rounded-2xl border border-line-strong/70 bg-surface px-3 text-base"
        >
          {available.map((s) => (
            <option key={s} value={s}>
              {LABELS[s]}
            </option>
          ))}
        </select>
        <Button variant="ghost" size="sm" onClick={() => nowPlayingPoller.refresh()}>
          Refresh now
        </Button>
      </div>
    </div>
  );
}
