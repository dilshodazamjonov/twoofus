/**
 * Soft, static colour fields behind every page (no animation, no blur filter:
 * cheap to paint on older phones).
 */
export function Backdrop() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10"
      style={{
        background:
          "radial-gradient(42rem 30rem at -8% -6%, var(--decor-a), transparent 70%)," +
          "radial-gradient(38rem 28rem at 108% 104%, var(--decor-b), transparent 70%)",
      }}
    />
  );
}
