// Display formatting. Timestamps are stored and sent as UTC; they are shown in
// the viewer's own time zone and language here, and only here.

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? null : ms;
}

/** "just now", "2 min ago", "3 h ago", "yesterday", or a date. */
export function formatRelative(thenMs: number, nowMs: number, locale?: string): string {
  const diff = Math.max(0, nowMs - thenMs);
  if (diff < 45 * SECOND) return "just now";
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto", style: "short" });
  if (diff < HOUR) return rtf.format(-Math.max(1, Math.round(diff / MINUTE)), "minute");
  if (diff < DAY) return rtf.format(-Math.round(diff / HOUR), "hour");
  if (diff < 7 * DAY) return rtf.format(-Math.round(diff / DAY), "day");
  return formatDate(thenMs, locale);
}

export function formatClock(ms: number, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).format(ms);
}

export function formatDate(ms: number, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" }).format(ms);
}

export function formatDateTime(ms: number, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(ms);
}

/** 187000 -> "3:07" */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`;
}

/** 187000 -> "3 minutes 7 seconds" (for screen readers) */
export function formatDurationSpoken(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  const parts: string[] = [];
  if (minutes) parts.push(`${minutes} minute${minutes === 1 ? "" : "s"}`);
  if (seconds || !minutes) parts.push(`${seconds} second${seconds === 1 ? "" : "s"}`);
  return parts.join(" ");
}

/** First word of a display name, for short labels. */
export function firstName(displayName: string): string {
  return displayName.trim().split(/\s+/)[0] || displayName;
}
