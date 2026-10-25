import path from "node:path";

/** Signed-in owner session, written by auth.setup.ts and reused by the tests (gitignored). */
export const OWNER_STATE = path.resolve(__dirname, "../playwright/.auth/owner.json");
/** For tests that need a signed-out browser. */
export const SIGNED_OUT = { cookies: [], origins: [] };
