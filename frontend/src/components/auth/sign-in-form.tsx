"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { applySession, sessionResource } from "@/lib/resources";
import { safeNextPath } from "@/lib/safe-next";
import { useResource } from "@/lib/store/resource";

import { PasswordField } from "./password-field";

function describe(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  if (error.code === "invalid_credentials") return "That username and password don't match.";
  if (error.status === 429) {
    const minutes = Math.max(1, Math.ceil((error.retryAfterSeconds ?? 60) / 60));
    return `Too many attempts. Please wait about ${minutes} minute${minutes === 1 ? "" : "s"} and try again.`;
  }
  if (error.isNetwork) return "You seem to be offline, or the server is unreachable.";
  return error.message;
}

export function SignInForm() {
  const params = useSearchParams();
  const router = useRouter();
  const session = useResource(sessionResource);
  const next = safeNextPath(params.get("next"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authenticated = session.data?.authenticated === true;
  useEffect(() => {
    if (authenticated) router.replace(next);
  }, [authenticated, next, router]);

  // A brand-new install has no account yet: say how the first one is made.
  const [notSetUp, setNotSetUp] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api
      .setupStatus({ signal: controller.signal })
      .then((status) => setNotSetUp(!status.owner_exists))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(username.trim(), password);
      setPassword("");
      applySession(result);
      router.replace(next);
    } catch (e) {
      setError(describe(e));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-5" noValidate>
      {params.get("expired") === "1" ? (
        <Alert tone="info" title="Please sign in again" />
      ) : null}
      {params.get("signed_out") === "1" ? <Alert tone="success" title="You're signed out." /> : null}
      {notSetUp ? (
        <Alert tone="info" title="Not set up yet">
          Create the first account on the server.
        </Alert>
      ) : null}
      <TextField
        label="Username"
        name="username"
        autoComplete="username"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        required
      />
      <PasswordField
        label="Password"
        name="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      {error ? (
        <p role="alert" className="text-[0.95rem] font-medium text-danger">
          {error}
        </p>
      ) : null}
      <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!username.trim() || !password}>
        Sign in
      </Button>
    </form>
  );
}
