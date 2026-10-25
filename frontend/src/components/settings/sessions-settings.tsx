"use client";

import { LogOut, MonitorSmartphone } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDate, formatRelative } from "@/lib/format";
import { applySession, sessionsResource } from "@/lib/resources";
import { useNow } from "@/lib/store/now";
import { useResource } from "@/lib/store/resource";
import { toast } from "@/lib/toast";

/** Where I'm signed in (times only: no device details are stored), and signing out. */
export function SessionsSettings() {
  const sessions = useResource(sessionsResource);
  const now = useNow(60_000);
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const list = sessions.data?.sessions ?? [];
  const others = list.filter((s) => !s.current);

  async function run(key: string, action: () => Promise<unknown>, done: string) {
    setBusy(key);
    try {
      await action();
      await sessionsResource.load();
      toast(done, "success");
    } catch (e) {
      if (!(e instanceof ApiError && e.isUnauthenticated)) {
        toast(e instanceof ApiError ? e.message : "Something went wrong. Please try again.", "error");
      }
    } finally {
      setBusy(null);
    }
  }

  async function signOut() {
    setBusy("me");
    try {
      applySession(await api.logout(), "signed_out");
      router.replace("/sign-in?signed_out=1");
    } catch {
      setBusy(null);
      toast("Couldn't sign out. Please try again.", "error");
    }
  }

  return (
    <div className="space-y-4">
      {sessions.status === "loading" || sessions.status === "idle" ? (
        <Skeleton className="h-20" />
      ) : (
        <ul className="divide-y divide-line rounded-2xl border border-line">
          {list.map((s) => (
            <li key={s.id} className="flex items-center gap-3 px-4 py-3">
              <MonitorSmartphone aria-hidden className="size-5 shrink-0 text-muted" />
              <div className="min-w-0 flex-1 text-[0.95rem]">
                <p className="font-medium">{s.current ? "This device" : "Another device or browser"}</p>
                <p className="text-sm text-muted">
                  Signed in {formatDate(Date.parse(s.created_at))}
                  {now !== null && !s.current ? ` · active ${formatRelative(Date.parse(s.last_seen_at), now)}` : ""}
                </p>
              </div>
              {!s.current ? (
                <Button
                  size="sm"
                  variant="ghost"
                  loading={busy === s.id}
                  disabled={busy !== null}
                  onClick={() => void run(s.id, () => api.revokeSession(s.id), "Signed out that device.")}
                >
                  Sign out
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        {others.length > 0 ? (
          <Button
            variant="secondary"
            loading={busy === "others"}
            disabled={busy !== null}
            onClick={() =>
              void run("others", () => api.revokeOtherSessions(), "Signed out everywhere else.")
            }
          >
            Sign out everywhere else
          </Button>
        ) : null}
        <Button
          variant="ghost"
          loading={busy === "me"}
          disabled={busy !== null}
          onClick={() => void signOut()}
          icon={<LogOut aria-hidden className="size-4" />}
        >
          Sign out of this device
        </Button>
      </div>
    </div>
  );
}
