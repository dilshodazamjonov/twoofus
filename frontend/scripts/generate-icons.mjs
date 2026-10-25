// Renders the original app artwork (assets/*.svg) into the PNG/ICO files that
// browsers and iOS need. Run after changing the artwork: `npm run icons`.
// Output is committed, so builds never depend on this script.
import { mkdirSync, readFileSync, writeFileSync, copyFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const root = fileURLToPath(new URL("..", import.meta.url));
const icon = readFileSync(`${root}/assets/app-icon.svg`);
const favicon = readFileSync(`${root}/assets/favicon.svg`);

async function png(svg, size) {
  // Render at the target size rather than scaling up a small raster.
  const width = Number(/viewBox="[\d.]+ [\d.]+ ([\d.]+)/.exec(svg.toString())?.[1] ?? 64);
  return sharp(svg, { density: Math.max(72, Math.ceil((size / width) * 72)) })
    .resize(size, size)
    .png({ compressionLevel: 9 })
    .toBuffer();
}

/** Pack PNG images into a .ico container (PNG-in-ICO, supported everywhere current). */
function ico(images) {
  const header = Buffer.alloc(6 + images.length * 16);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach(({ size, data }, i) => {
    const entry = 6 + i * 16;
    header.writeUInt8(size >= 256 ? 0 : size, entry);
    header.writeUInt8(size >= 256 ? 0 : size, entry + 1);
    header.writeUInt8(0, entry + 2);
    header.writeUInt8(0, entry + 3);
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(data.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += data.length;
  });
  return Buffer.concat([header, ...images.map((image) => image.data)]);
}

mkdirSync(`${root}/public/icons`, { recursive: true });
writeFileSync(`${root}/public/icons/icon-192.png`, await png(icon, 192));
writeFileSync(`${root}/public/icons/icon-512.png`, await png(icon, 512));
// The artwork keeps everything inside the 80% safe zone, so it doubles as maskable.
writeFileSync(`${root}/public/icons/icon-maskable-512.png`, await png(icon, 512));
writeFileSync(`${root}/src/app/apple-icon.png`, await png(icon, 180));
copyFileSync(`${root}/assets/favicon.svg`, `${root}/src/app/icon.svg`);
writeFileSync(
  `${root}/src/app/favicon.ico`,
  ico(await Promise.all([16, 32, 48].map(async (size) => ({ size, data: await png(favicon, size) })))),
);
console.log("Icons written to public/icons and src/app.");
