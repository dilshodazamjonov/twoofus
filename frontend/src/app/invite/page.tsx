import { InviteAccept } from "@/components/auth/invite-accept";
import { PublicFrame } from "@/components/auth/public-frame";

export const metadata = { title: "Your invitation" };

export default function InvitePage() {
  return (
    <PublicFrame>
      <InviteAccept />
    </PublicFrame>
  );
}
