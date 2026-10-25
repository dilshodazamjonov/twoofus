// Only ever redirect to our own pages after sign-in (no open redirects).
const ALLOWED = ["/room", "/connect", "/settings"];

export function safeNextPath(value: string | null | undefined, fallback = "/room"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return fallback;
  try {
    const url = new URL(value, "http://local.invalid");
    if (url.origin !== "http://local.invalid") return fallback;
    if (!ALLOWED.some((path) => url.pathname === path || url.pathname.startsWith(`${path}/`))) return fallback;
    return `${url.pathname}${url.search}`;
  } catch {
    return fallback;
  }
}
