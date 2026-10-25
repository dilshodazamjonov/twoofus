"use client";

import { Copy, ExternalLink, FlaskConical } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { DeviceFlowOut } from "@/lib/api/types";
import { formatDuration } from "@/lib/format";
import { nowPlayingPoller, providersResource } from "@/lib/resources";
import { useNow } from "@/lib/store/now";
import { toast } from "@/lib/toast";

/** Only ever link to Yandex's own sign-in pages. */
export function isYandexUrl(value: string | null): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && /(^|\.)(ya\.ru|yandex\.(ru|com|by|kz|uz|com\.tr))$/.test(url.hostname);
  } catch {
    return false;
  }
}

const FAILURES: Record<string, string> = {
  access_denied: "The approval was declined on Yandex's page.",
  expired: "That code expired before it was approved.",
  cancelled: "You cancelled this attempt.",
};

/**
 * Yandex device flow (experimental, unofficial): the backend shows a short
 * code; she approves it on Yandex's own page; this component polls the
 * backend at Yandex's interval while the page is visible.
 */
export function YandexConnect({ resume }: { resume: boolean }) {
  const [flow, setFlow] = useState<DeviceFlowOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const now = useNow(1000);
  const resumed = useRef(false);

  const poll = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await api.yandexPoll({ signal });
      setFlow(next);
      if (next.status === "completed") {
        toast("Yandex Music is connected.", "success");
        void providersResource.load();
        nowPlayingPoller.refresh();
      }
    } catch (e) {
      if (signal?.aborted) return;
      if (e instanceof ApiError && e.code === "no_pending_authorization") setFlow(null);
    }
  }, []);

  // Pick up a code that was already showing (e.g. after switching apps to approve it).
  useEffect(() => {
    if (!resume || resumed.current) return;
    resumed.current = true;
    const controller = new AbortController();
    void poll(controller.signal);
    return () => controller.abort();
  }, [resume, poll]);

  // While a code is pending and the page is visible, ask the backend at Yandex's pace.
  useEffect(() => {
    if (flow?.status !== "pending") return;
    const controller = new AbortController();
    let timer = 0;
    const schedule = () => {
      timer = window.setTimeout(async () => {
        if (document.visibilityState === "visible") await poll(controller.signal);
        if (!controller.signal.aborted) schedule();
      }, Math.max(3, flow.poll_interval_seconds) * 1000);
    };
    schedule();
    const onVisible = () => {
      if (document.visibilityState === "visible") void poll(controller.signal);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [flow?.status, flow?.poll_interval_seconds, poll]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setFlow(await api.yandexStart());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't reach Yandex. Please try again in a minute.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      await api.yandexCancel();
      setFlow(null);
    } catch {
      setFlow(null);
    } finally {
      setBusy(false);
    }
  }

  async function copyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      toast("Code copied.", "success");
    } catch {
      toast("Couldn't copy. Please type the code instead.", "info");
    }
  }

  const expiresIn = flow && now !== null ? Date.parse(flow.expires_at) - now : null;
  const pending = flow?.status === "pending";

  return (
    <div className="space-y-5">
      {pending && flow.user_code ? (
        <div className="rounded-2xl border border-line bg-surface-2 p-5">
          <ol className="space-y-4 text-[0.97rem]">
            <li>
              <span className="font-semibold">1. Open Yandex&apos;s page</span>
              {isYandexUrl(flow.verification_url) ? (
                <a
                  href={flow.verification_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 flex min-h-11 w-fit items-center gap-2 rounded-full bg-accent px-5 font-medium text-accent-ink"
                >
                  Open {new URL(flow.verification_url).hostname}
                  <ExternalLink aria-hidden className="size-4" />
                  <span className="sr-only">(opens Yandex in a new tab)</span>
                </a>
              ) : (
                <p className="mt-1 text-muted">Open the address Yandex shows for device sign-in.</p>
              )}
            </li>
            <li>
              <span className="font-semibold">2. Sign in there and enter this code</span>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <output
                  aria-label={`Code: ${flow.user_code.split("").join(" ")}`}
                  className="rounded-xl bg-surface px-4 py-2 font-mono text-2xl font-semibold tracking-[0.18em] text-ink"
                >
                  {flow.user_code}
                </output>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void copyCode(flow.user_code!)}
                  icon={<Copy aria-hidden className="size-4" />}
                >
                  Copy code
                </Button>
              </div>
            </li>
            <li>
              <span className="font-semibold">3. Come back here</span>
              <p className="mt-1 text-muted" aria-live="polite">
                {expiresIn !== null && expiresIn > 0 ? `Expires in ${formatDuration(expiresIn)}.` : null}
              </p>
            </li>
          </ol>
          <Button variant="ghost" size="sm" className="mt-3" onClick={() => void cancel()} disabled={busy}>
            Cancel
          </Button>
        </div>
      ) : null}

      {flow && (flow.status === "failed" || flow.status === "expired" || flow.status === "cancelled") ? (
        <Alert tone="info" title="Not connected">
          {FAILURES[flow.error_code ?? flow.status] ?? "Yandex didn't confirm the connection."} You can try again.
        </Alert>
      ) : null}
      {flow?.status === "completed" ? <Alert tone="success" title="Connected to Yandex Music" /> : null}
      {error ? <Alert tone="error">{error}</Alert> : null}

      {!pending && flow?.status !== "completed" ? (
        <div className="space-y-3">
          <Button size="lg" onClick={() => void start()} loading={busy} icon={<FlaskConical aria-hidden className="size-4" />}>
            {flow ? "Get a new code" : "Get a code from Yandex"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
