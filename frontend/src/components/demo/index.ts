// Development-only demo UI. Imported only as "@demo-ui": next.config.ts points
// that alias here when TWOOFUS_DEMO_UI=1 (next dev, e2e and smoke builds) and
// at ./off.ts otherwise, so a production bundle contains none of this code
// (scripts/check-bundle.mjs verifies it).
export { DemoConnect } from "../connect/demo-connect";
export { DemoControls } from "../settings/demo-controls";

export const DEMO_OPTION: { label: string; hint: string } | null = {
  label: "Demo songs",
  hint: "Invented songs, for testing",
};
