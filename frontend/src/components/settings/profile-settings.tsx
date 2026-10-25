"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { nowPlayingPoller, roomResource, sessionResource } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";
import { toast } from "@/lib/toast";

export function ProfileSettings() {
  const session = useResource(sessionResource);
  const user = session.data?.user ?? null;
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const value = draft ?? user?.display_name ?? "";

  async function submit(event: FormEvent) {
    event.preventDefault();
    const name = value.trim().replace(/\s+/g, " ");
    if (!name) {
      setError("Please enter a name.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateProfile(name);
      const current = sessionResource.getSnapshot().data;
      if (current) sessionResource.mutate({ ...current, user: updated });
      setDraft(null);
      void roomResource.load();
      nowPlayingPoller.refresh();
      toast("Name updated.", "success");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4">
      <TextField
        label="Your name"
        hint={`Username: ${user?.username ?? "…"}`}
        value={value}
        onChange={(e) => setDraft(e.target.value)}
        maxLength={40}
        autoComplete="nickname"
        required
        error={error}
      />
      <Button type="submit" variant="secondary" loading={busy} disabled={draft === null || value.trim() === user?.display_name}>
        Save name
      </Button>
    </form>
  );
}
