"use client";

// Last-resort boundary (the root layout itself failed): plain HTML, inline styles.
export default function GlobalError({ retry }: { error: unknown; retry: () => void }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100dvh",
          display: "grid",
          placeItems: "center",
          background: "#FFF9F5",
          color: "#302B2D",
          fontFamily: "ui-sans-serif, system-ui, -apple-system, sans-serif",
          padding: 24,
          textAlign: "center",
        }}
      >
        <main>
          <h1 style={{ fontFamily: "Georgia, serif", fontWeight: 600 }}>Something went wrong</h1>
          <button
            type="button"
            onClick={retry}
            style={{
              minHeight: 48,
              padding: "0 24px",
              borderRadius: 999,
              border: 0,
              background: "#813F59",
              color: "#fff",
              fontWeight: 600,
            }}
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
