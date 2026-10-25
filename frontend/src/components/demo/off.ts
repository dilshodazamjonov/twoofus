// Stands in for ./index.ts in builds without the demo UI (see next.config.ts).
export function DemoConnect(): null {
  return null;
}

export function DemoControls(): null {
  return null;
}

export const DEMO_OPTION: { label: string; hint: string } | null = null;
