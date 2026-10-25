"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { TextField } from "@/components/ui/text-field";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { applySession } from "@/lib/resources";

export function DeleteAccount() {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.deleteAccount(password);
      setPassword("");
      applySession({ authenticated: false, csrf_token: "", session_expired: false }, "signed_out");
      router.replace("/?deleted=1");
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "wrong_password"
          ? "That password isn't right."
          : e instanceof ApiError
            ? e.message
            : "Couldn't delete the account. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <Button variant="danger" onClick={() => setOpen(true)}>
        Delete my account…
      </Button>
      <Dialog
        open={open}
        onClose={() => {
          setOpen(false);
          setPassword("");
          setError(null);
        }}
        title="Delete your account?"
        description="This can't be undone."
      >
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          <TextField
            label="Password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            error={error}
          />
          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Keep my account
            </Button>
            <Button type="submit" variant="danger" loading={busy} disabled={!password}>
              Delete forever
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
