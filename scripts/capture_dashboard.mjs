/**
 * Capture the dashboard screenshots the README embeds.
 *
 * Playwright rather than a headless-browser invocation: it ships its own pinned Chromium,
 * waits for web fonts to settle instead of guessing at a sleep, and takes a real full-page
 * shot rather than needing the height passed in. The images are therefore reproducible,
 * which is the same standard every number in this repo is held to.
 *
 *   node scripts/capture_dashboard.mjs
 */
import { spawn } from 'node:child_process';
import { mkdirSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = resolve(ROOT, 'docs/assets');
const PORT = Number(process.env.PORT ?? 4399);
const BASE = `http://127.0.0.1:${PORT}`;

/** 1440 is where the two-column comparison and the bled wordmark both read as intended. */
const VIEWPORT = { width: 1440, height: 1000 };
const SCALE = 2;

/**
 * `clipHeight` crops from the top of the page; `section` instead screenshots the one band
 * whose heading matches, which keeps a figure pointed at its own content even when the
 * page above it grows.
 */
const SHOTS = [
  { path: '/', file: 'landing.png', clipHeight: 1560 },
  { path: '/', file: 'landing-value.png', section: 'What the guarantee is worth' },
  { path: '/evidence/', file: 'dashboard-evidence.png', clipHeight: 1300 },

  // The submission set, in the order the story is told: the problem, the router catching
  // a real hook, what it does instead, why that cannot be gamed, and the evidence behind
  // it. Numbered so they stay in order in a file picker.
  { path: '/', file: 'submission-1-problem.png', clipHeight: 1100 },
  { path: '/', file: 'submission-2-catch.png', section: 'The same swap, priced two ways' },
  { path: '/', file: 'submission-3-solution.png', section: 'Ask once.' },
  {
    path: '/',
    file: 'submission-4-defence.png',
    section: 'Why a hook cannot tell it is being probed',
  },
  {
    path: '/evidence/',
    file: 'submission-5-hooks.png',
    section: 'The hooks that charge more than they quote',
  },
  { path: '/evidence/', file: 'submission-6-attribution.png', section: 'Everyone is routing into them' },
];

async function waitForServer(url, attempts = 40) {
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`static server never came up on ${url}`);
}

async function main() {
  mkdirSync(OUT, { recursive: true });

  const server = spawn('npx', ['--yes', 'serve', 'app/out', '-l', String(PORT)], {
    cwd: ROOT,
    stdio: 'ignore',
  });
  const stop = () => server.kill();
  process.on('exit', stop);
  process.on('SIGINT', () => {
    stop();
    process.exit(1);
  });

  try {
    await waitForServer(`${BASE}/`);

    const browser = await chromium.launch();
    const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: SCALE });

    for (const shot of SHOTS) {
      const res = await page.goto(BASE + shot.path, { waitUntil: 'networkidle' });
      if (!res || !res.ok()) throw new Error(`${shot.path} returned ${res?.status()}`);

      // Web fonts change every measurement on the page, so capturing before they settle
      // produces a screenshot of a layout that never existed.
      await page.evaluate(() => document.fonts.ready);
      // The landing page animates on load; wait for the sequence to settle so the shot
      // shows the state a reader ends up looking at, not a frame mid-count.
      await page.waitForTimeout(2600);

      const target = resolve(OUT, shot.file);
      if (shot.section) {
        const band = page.locator('.band, .panel', { hasText: shot.section }).first();
        if ((await band.count()) === 0) throw new Error(`no band matching "${shot.section}"`);
        // Sections on the landing reveal themselves when scrolled to, so a shot taken
        // without scrolling captures a transparent element. 14 KB of nothing.
        await band.scrollIntoViewIfNeeded();
        await page.waitForTimeout(800);
        const opacity = await band.evaluate((el) => getComputedStyle(el).opacity);
        if (Number(opacity) < 0.99) {
          throw new Error(`"${shot.section}" was still at opacity ${opacity} when captured`);
        }
        await band.screenshot({ path: target });
      } else {
        // A full-page shot of a long dashboard is unreadable in a README; crop to the part
        // that makes the point, at the page's own width.
        await page.screenshot({
          path: target,
          clip: { x: 0, y: 0, width: VIEWPORT.width, height: shot.clipHeight },
        });
      }
      const kb = Math.round(statSync(target).size / 1024);
      console.log(
        `  docs/assets/${shot.file}  ${shot.section ? `section "${shot.section}"` : `${VIEWPORT.width}x${shot.clipHeight}`} @${SCALE}x  ${kb} KB`,
      );
    }

    await browser.close();
  } finally {
    stop();
  }
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
