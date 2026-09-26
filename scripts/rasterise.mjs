/**
 * SVG -> PNG, through the browser that already ships with this repo.
 *
 * Submission forms and slide decks take PNG, not SVG, and no rasteriser (rsvg, inkscape,
 * cairosvg) is a safe assumption on a contributor's machine. Playwright is already a
 * dependency for the dashboard captures, and rendering the SVG in Chromium gets the same
 * text shaping the site uses rather than a fallback font.
 */
import { chromium } from 'playwright';
import { readFile, writeFile, stat } from 'node:fs/promises';
import path from 'node:path';

const ASSETS = 'docs/assets';

// [source svg, output png, css pixel width] - height follows the SVG's own ratio.
const TARGETS = [
  ['banner.svg', 'banner.png', 1280],
  ['logo-seal.svg', 'logo.png', 1024],
  ['logo-wordmark.svg', 'logo-wordmark.png', 960],
  ['routing.svg', 'routing.png', 1400],
  ['mechanism.svg', 'mechanism.png', 1400],
  ['attack.svg', 'attack.png', 1400],
];

const browser = await chromium.launch();
for (const [src, out, width] of TARGETS) {
  const svg = await readFile(path.join(ASSETS, src), 'utf8');
  const vb = svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);
  if (!vb) throw new Error(`${src} has no viewBox`);
  const ratio = Number(vb[2]) / Number(vb[1]);
  const height = Math.round(width * ratio);

  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 2,
  });
  // Transparent ground, so a logo with no plate stays transparent.
  await page.setContent(
    `<!doctype html><meta charset="utf-8">
     <style>html,body{margin:0;padding:0;background:transparent}
     svg{display:block;width:${width}px;height:${height}px}</style>${svg}`,
    { waitUntil: 'load' },
  );
  await page.waitForTimeout(150);
  await page.screenshot({ path: path.join(ASSETS, out), omitBackground: true });
  await page.close();

  const kb = Math.round((await stat(path.join(ASSETS, out))).size / 1024);
  console.log(`  ${ASSETS}/${out}  ${width}x${height} @2x  ${kb} KB`);
}
await browser.close();
