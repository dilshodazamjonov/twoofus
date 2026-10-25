// Content-Security-Policy for every page, with a fresh nonce per request
// (src/proxy.ts). Next.js reads the nonce from the request's CSP header and puts
// it on its own scripts; 'strict-dynamic' lets those load the rest. Nothing
// else may run: no inline handlers, no third-party scripts, no eval in
// production.

// Hosts album artwork may come from. The backend only ever passes https URLs on
// exactly these hosts (backend/app/providers/urls.py); a backend test checks
// that the two lists stay the same.
export const ARTWORK_HOSTS = ["scdn.co", "spotifycdn.com", "yandex.net"] as const;

export function contentSecurityPolicy(nonce: string, { dev = false }: { dev?: boolean } = {}): string {
  const artwork = ARTWORK_HOSTS.flatMap((host) => [`https://${host}`, `https://*.${host}`]);
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    // React and our CSS use style attributes (progress bars, safe areas).
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: ${artwork.join(" ")}`,
    "font-src 'self'",
    `connect-src 'self'${dev ? " ws: wss:" : ""}`,
    "worker-src 'self'",
    "manifest-src 'self'",
    "media-src 'none'",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ].join("; ");
}

/** 128 random bits, base64 (CSP nonce syntax). */
export function newNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
