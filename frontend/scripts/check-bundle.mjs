// Checks a production build for things that must never ship to a deployment:
//   * the development-only demo UI (it is swapped out at build time, see
//     next.config.ts and src/components/demo/);
//   * server-only values in browser bundles (the proxy secret, the backend URL).
//
//   node scripts/check-bundle.mjs [distDir]        (default: .next)
// Exits 1 with a list of findings. Source maps are skipped: they are not served.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const distDir = process.argv[2] ?? ".next";
const DEMO_MARKERS = ["/api/v1/providers/demo/", "Use demo songs", "Invented songs, for testing"];

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* files(path);
    else if (/\.(js|html|json|rsc|body)$/.test(name) && !name.endsWith(".map")) yield path;
  }
}

const findings = [];
const browserSecrets = [process.env.TWOOFUS_PROXY_SECRET, process.env.BACKEND_INTERNAL_URL].filter(
  (value) => value && value.length >= 8,
);

for (const path of files(distDir)) {
  const text = readFileSync(path, "utf8");
  for (const marker of DEMO_MARKERS) {
    if (text.includes(marker)) findings.push(`${path}: demo UI marker ${JSON.stringify(marker)}`);
  }
  if (path.includes(`${distDir}/static/`)) {
    for (const secret of browserSecrets) {
      if (text.includes(secret)) findings.push(`${path}: a server-only value is in a browser bundle`);
    }
  }
}

if (findings.length > 0) {
  console.error(`Bundle check failed (${distDir}):\n  ${findings.join("\n  ")}`);
  process.exit(1);
}
console.log(`Bundle check passed (${distDir}): no demo UI, no server-only values in browser bundles.`);
