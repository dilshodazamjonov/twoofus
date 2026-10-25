// The development-only demo UI (the "Demo songs" option and Settings' demo
// scenario picker) is compiled in only when TWOOFUS_DEMO_UI=1 at build time.
// next.config.ts turns it on for `next dev` and the e2e/smoke builds; the
// production image builds without it, so its bundles contain no demo controls
// (scripts/check-bundle.mjs fails the build check if any slip in). The server
// independently refuses DEMO_MODE in production.
export const DEMO_UI = process.env.TWOOFUS_DEMO_UI === "1";
