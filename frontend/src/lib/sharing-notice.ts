// What a member acknowledges before turning "Share my music" on. The backend
// requires the matching SHARING_NOTICE_VERSION (backend/app/core/config.py);
// change both together whenever this text changes.
export const SHARING_NOTICE_VERSION = "2026-10-25.2";

export function sharingNotice(partnerName: string | null): string[] {
  const who = partnerName ?? "The other person";
  return [
    `${who} will see the song you're playing (title, artists, album, cover) while the app is open.`,
    "No history is kept. You can turn this off at any time.",
  ];
}
