import { ButtonLink } from "@/components/ui/button";
import { LogoMark } from "@/components/brand/logo-mark";

export const metadata = { title: "Not found" };

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
      <LogoMark className="size-16" />
      <h1 className="font-display text-4xl font-semibold">Page not found</h1>
      <ButtonLink href="/room" className="mt-2">
        Back home
      </ButtonLink>
    </main>
  );
}
