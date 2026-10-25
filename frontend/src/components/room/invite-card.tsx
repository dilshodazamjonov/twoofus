import { UserPlus } from "lucide-react";

import { ButtonLink } from "@/components/ui/button";

export function InviteCard({ isOwner, invitationPending }: { isOwner: boolean; invitationPending: boolean }) {
  return (
    <article className="flex flex-col items-start justify-center gap-3 rounded-[1.75rem] border border-dashed border-line-strong/50 bg-surface/70 p-6">
      <span className="inline-flex size-11 items-center justify-center rounded-full bg-accent-soft text-accent-text">
        <UserPlus aria-hidden className="size-5" />
      </span>
      <h2 className="font-display text-2xl font-semibold">{invitationPending ? "Invite pending" : "Nobody else yet"}</h2>
      {isOwner ? (
        <ButtonLink href="/settings#person" variant="soft" size="sm">
          {invitationPending ? "Manage invite" : "Create invite link"}
        </ButtonLink>
      ) : null}
    </article>
  );
}
