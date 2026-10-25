import { FoundationStatus } from "./foundation-status";

// Phase 1 placeholder. The real interface (cards, consent flow, PWA) is built
// in Phase 2; this page only proves the same-origin /api proxy works.
export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-2">
        <p className="text-sm uppercase tracking-[0.2em] text-stone-500">Foundation</p>
        <h1 className="text-3xl font-semibold tracking-tight text-stone-900 dark:text-stone-100">
          Two of Us
        </h1>
        <p className="text-stone-600 dark:text-stone-400">
          The backend, sign-in and music connections are in place. The full interface arrives in the
          next phase.
        </p>
      </header>
      <FoundationStatus />
    </main>
  );
}
