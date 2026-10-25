"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { demoApi } from "@/lib/api/demo";
import { nowPlayingPoller, providersResource } from "@/lib/resources";
import { toast } from "@/lib/toast";

export function DemoConnect() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      await demoApi.connect();
      await providersResource.load();
      nowPlayingPoller.refresh();
      toast("Demo songs connected.", "success");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't connect the demo.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <Button size="lg" variant="secondary" onClick={() => void connect()} loading={busy}>
        Use demo songs
      </Button>
    </div>
  );
}
