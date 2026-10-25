import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { PublicFrame } from "@/components/auth/public-frame";

export const metadata = { title: "Privacy" };

const STORED = [
  "Your username, name and a password hash",
  "Sign-in sessions (dates only)",
  "Whether sharing is on",
  "Your Spotify or Yandex Music access, encrypted",
  "Tulips, deleted after 7 days",
] as const;

export default function PrivacyPage() {
  return (
    <PublicFrame footer={false}>
      <Link href="/" className="mb-6 inline-flex min-h-11 w-fit items-center gap-2 text-sm font-medium text-accent-text">
        <ArrowLeft aria-hidden className="size-4" />
        Back
      </Link>
      <h1 className="font-display text-[2.5rem] font-semibold leading-tight">Privacy</h1>
      <h2 className="mt-6 font-display text-2xl font-semibold">Stored</h2>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-[0.97rem] text-muted">
        {STORED.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <h2 className="mt-6 font-display text-2xl font-semibold">Never stored</h2>
      <p className="mt-3 text-[0.97rem] text-muted">
        Listening history. Songs are shown live and only while sharing is on. Deleting your account removes your data.
      </p>
    </PublicFrame>
  );
}
