"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TextField } from "@/components/ui/text-field";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { InvitationInspectOut } from "@/lib/api/types";
import { useInviteToken } from "@/lib/invite-token";
import { applySession, sessionResource } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";

import { PasswordField } from "./password-field";

type Inspection =
  | { state: "checking" }
  | { state: "valid"; invitation: InvitationInspectOut }
  | { state: "invalid" }
  | { state: "error"; message: string };

const USERNAME_RULE = /^[a-z0-9][a-z0-9_.-]{2,31}$/;

export function InviteAccept() {
  const token = useInviteToken();
  const session = useResource(sessionResource);
  const router = useRouter();
  const [inspection, setInspection] = useState<Inspection>({ state: "checking" });
  const [form, setForm] = useState({ displayName: "", username: "", password: "", confirm: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof typeof form | "form", string>>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    api
      .inspectInvitation(token)
      .then((invitation) => {
        if (!controller.signal.aborted) setInspection({ state: "valid", invitation });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.code === "invitation_invalid") setInspection({ state: "invalid" });
        else if (e instanceof ApiError && e.status === 429)
          setInspection({ state: "error", message: "Too many attempts. Please wait a few minutes and open the link again." });
        else setInspection({ state: "error", message: e instanceof ApiError ? e.message : "Couldn't check the invitation." });
      });
    return () => controller.abort();
  }, [token]);

  if (token === undefined) return <Skeleton className="h-72 rounded-[1.75rem]" />;
  if (token === null) {
    return (
      <Alert tone="info" title="This link looks incomplete">
      </Alert>
    );
  }
  if (session.data?.authenticated) {
    return <AlreadySignedIn name={session.data.user?.display_name ?? "someone"} />;
  }
  if (inspection.state === "checking") return <Skeleton className="h-72 rounded-[1.75rem]" />;
  if (inspection.state === "invalid") {
    return (
      <Alert tone="info" title="This invitation can't be used">
        Ask for a new link.
      </Alert>
    );
  }
  if (inspection.state === "error") return <Alert tone="error">{inspection.message}</Alert>;

  const { invitation } = inspection;
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  function validate(): boolean {
    const next: typeof errors = {};
    if (!form.displayName.trim()) next.displayName = "Please enter a name.";
    if (!USERNAME_RULE.test(form.username.trim().toLowerCase()))
      next.username = "3–32 characters: letters, digits, “.”, “_” or “-”, starting with a letter or digit.";
    if (form.password.length < 10) next.password = "At least 10 characters.";
    if (form.confirm !== form.password) next.confirm = "The passwords don't match.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!token || !validate()) return;
    setBusy(true);
    try {
      const result = await api.acceptInvitation({
        token,
        username: form.username.trim().toLowerCase(),
        display_name: form.displayName.trim(),
        password: form.password,
      });
      setForm({ displayName: "", username: "", password: "", confirm: "" });
      applySession(result);
      window.history.replaceState(null, "", "/invite"); // the used token leaves the address bar
      router.replace("/connect");
    } catch (e) {
      setBusy(false);
      if (!(e instanceof ApiError)) {
        setErrors({ form: "Something went wrong. Please try again." });
        return;
      }
      if (e.code === "username_taken") setErrors({ username: "That username is taken. Try another one." });
      else if (e.code === "invalid_username") setErrors({ username: e.message });
      else if (e.code === "weak_password") setErrors({ password: e.message });
      else if (e.code === "invalid_display_name") setErrors({ displayName: e.message });
      else if (e.code === "invitation_invalid") setInspection({ state: "invalid" });
      else setErrors({ form: e.status === 429 ? "Too many attempts. Please wait a few minutes." : e.message });
    }
  }

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h1 className="font-display text-[2.4rem] font-semibold leading-tight">
          {invitation.inviter_display_name} invited you
        </h1>
      </div>
      <form
        onSubmit={(e) => void submit(e)}
        className="space-y-5 rounded-[1.75rem] border border-line bg-surface p-5 shadow-card sm:p-6"
        noValidate
      >
        <TextField
          label="Your name"
          autoComplete="nickname"
          maxLength={40}
          value={form.displayName}
          onChange={set("displayName")}
          error={errors.displayName}
          required
        />
        <TextField
          label="Username"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          maxLength={32}
          value={form.username}
          onChange={set("username")}
          error={errors.username}
          required
        />
        <PasswordField
          label="Password"
          autoComplete="new-password"
          value={form.password}
          onChange={set("password")}
          hint="At least 10 characters."
          error={errors.password}
          required
        />
        <PasswordField
          label="Confirm password"
          autoComplete="new-password"
          value={form.confirm}
          onChange={set("confirm")}
          error={errors.confirm}
          required
        />
        {errors.form ? (
          <p role="alert" className="text-[0.95rem] font-medium text-danger">
            {errors.form}
          </p>
        ) : null}
        <Button type="submit" size="lg" className="w-full" loading={busy}>
          Create account
        </Button>
      </form>
    </div>
  );
}

function AlreadySignedIn({ name }: { name: string }) {
  const [busy, setBusy] = useState(false);
  async function signOut() {
    setBusy(true);
    try {
      applySession(await api.logout(), "signed_out");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Alert tone="info" title={`You're signed in as ${name}`}>
      <div className="mt-3">
        <Button size="sm" variant="secondary" loading={busy} onClick={() => void signOut()} icon={<LogOut aria-hidden className="size-4" />}>
          Sign out and continue
        </Button>
      </div>
    </Alert>
  );
}
