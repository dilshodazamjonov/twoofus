"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Card, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { DEFAULT_APP_NAME } from "@/lib/app-name";
import { DEMO_UI } from "@/lib/demo-ui";
import { PROVIDERS } from "@/lib/providers";
import { configResource, providersResource, roomResource } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";

import { DemoControls } from "@demo-ui";

import { DeleteAccount } from "./delete-account";
import { InstallHelp } from "./install-help";
import { PersonSettings } from "./person-settings";
import { ProfileSettings } from "./profile-settings";
import { SessionsSettings } from "./sessions-settings";
import { SharingSettings } from "./sharing-settings";

export function SettingsView() {
  const config = useResource(configResource);
  const room = useResource(roomResource);
  const providers = useResource(providersResource);
  const appName = config.data?.app_name ?? DEFAULT_APP_NAME;
  const connection = providers.data?.connection ?? null;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-display text-[2.5rem] font-semibold leading-[1.05] sm:text-5xl">Settings</h1>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card aria-labelledby="profile-heading">
          <CardTitle id="profile-heading">You</CardTitle>
          <div className="mt-4">
            <ProfileSettings />
          </div>
        </Card>

        <Card aria-labelledby="music-heading">
          <CardTitle id="music-heading">Music service</CardTitle>
          <div className="mt-4 space-y-3">
            {providers.status === "loading" || providers.status === "idle" ? (
              <Skeleton className="h-12" />
            ) : connection ? (
              <div className="flex flex-wrap items-center gap-2 text-[0.97rem]">
                <span className="font-semibold">{PROVIDERS[connection.provider].label}</span>
                {connection.status === "reauth_required" ? (
                  <Chip tone="warning">Needs reconnecting</Chip>
                ) : (
                  <Chip tone="sage">Connected</Chip>
                )}
              </div>
            ) : (
              <p className="text-[0.97rem] text-muted">Not connected yet.</p>
            )}
            <Link
              href="/connect"
              className="inline-flex min-h-11 items-center gap-1.5 font-medium text-accent-text underline-offset-4 hover:underline"
            >
              {connection ? "Manage" : "Connect your music"}
              <ArrowRight aria-hidden className="size-4" />
            </Link>
            {DEMO_UI && config.data?.demo_controls && connection?.provider === "demo" ? <DemoControls /> : null}
          </div>
        </Card>
      </div>

      <Card aria-labelledby="sharing-settings-heading">
        <CardTitle id="sharing-settings-heading">Sharing</CardTitle>
        <div className="mt-5">
          <SharingSettings />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card id="person" aria-labelledby="person-heading" className="scroll-mt-24">
          <CardTitle id="person-heading">Invite</CardTitle>
          <div className="mt-4">
            {room.data ? <PersonSettings /> : <Skeleton className="h-16" />}
          </div>
        </Card>

        <Card aria-labelledby="install-heading">
          <CardTitle id="install-heading">Home Screen</CardTitle>
          <div className="mt-4">
            <InstallHelp appName={appName} />
          </div>
        </Card>
      </div>

      <Card aria-labelledby="sessions-heading">
        <CardTitle id="sessions-heading">Sessions</CardTitle>
        <div className="mt-4">
          <SessionsSettings />
        </div>
      </Card>

      <Card aria-labelledby="delete-heading" className="border-danger/30">
        <CardTitle id="delete-heading">Delete account</CardTitle>
        <div className="mt-3">
          <DeleteAccount />
        </div>
      </Card>

      <p className="text-center text-sm">
        <Link href="/privacy" className="text-muted underline-offset-4 hover:underline">
          Privacy
        </Link>
      </p>
    </div>
  );
}
