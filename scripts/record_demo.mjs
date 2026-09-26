/**
 * Record the walkthrough video: terminal scenes from a real demo run, then the live site.
 *
 *   node scripts/record_demo.mjs
 *
 * Everything on screen is real. The terminal scenes replay output captured from an actual
 * `scripts/demo.sh` run (`--capture` re-runs it), so the numbers are the ones the EVM
 * produced, not a mock-up. The site scenes are the built static export, served locally.
 *
 * One Playwright page for the whole thing, because a page records to one video file, so
 * the cuts happen inside the page rather than in an editor. The result is silent and
 * paced for narration: no on-screen prose the narrator would have to talk over.
 *
 * Output: docs/assets/sworn-demo.mp4 (and the raw .webm beside it if ffmpeg is missing).
 */
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, existsSync, rmSync, renameSync, readdirSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = resolve(ROOT, 'docs/assets');
const RAW = resolve(ROOT, '.video-raw');
const TRANSCRIPT = resolve(ROOT, 'docs/demo-transcript.txt');
const PORT = Number(process.env.PORT ?? 4398);
const BASE = `http://127.0.0.1:${PORT}`;

/** 16:9 at the width the site is designed for. */
const SIZE = { width: 1440, height: 810 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ------------------------------------------------------------------ the terminal scene */

const SHELL = `<!doctype html><meta charset="utf-8"><style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@400;500;700&display=swap');
  :root {
    --paper:#0d1014; --sheet:#141a21; --ink:#f2f4f6; --ink2:#9ba5af;
    --faint:#6c7680; --rule:#1e252e; --signal:#f04a10; --good:#4ade80;
    --mono:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;
    --sans:'Space Grotesk',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:var(--paper); color:var(--ink);
              font-family:var(--sans); overflow:hidden; }
  .wrap { height:100%; display:flex; flex-direction:column; padding:44px 56px; }
  .chrome { display:flex; align-items:center; gap:8px; padding-bottom:18px; }
  .dot { width:11px; height:11px; border-radius:50%; background:var(--rule); }
  .title { margin-left:14px; font-family:var(--mono); font-size:12.5px; color:var(--faint); }
  pre { flex:1; margin:0; font-family:var(--mono); font-size:15px; line-height:1.62;
        white-space:pre-wrap; overflow:hidden; }
  .cmd  { color:var(--ink); font-weight:700; }
  .step { color:var(--ink2); }
  .ok   { color:var(--good); }
  .beat { color:var(--faint); }
  .sig  { color:var(--signal); font-weight:700; }
  .dim  { color:var(--faint); }
  .cursor { display:inline-block; width:9px; height:17px; background:var(--signal);
            vertical-align:-3px; animation:b 1s steps(2) infinite; }
  @keyframes b { 50% { opacity:0 } }

  /* Full-bleed cards between scenes. */
  .card { position:fixed; inset:0; background:var(--paper); display:flex;
          flex-direction:column; justify-content:center; padding:0 120px; gap:22px;
          opacity:0; transition:opacity .5s ease; pointer-events:none; }
  .card.on { opacity:1; }
  .card h1 { margin:0; font-size:66px; font-weight:700; letter-spacing:-2.4px; line-height:1.06; }
  .card p  { margin:0; font-size:23px; color:var(--ink2); max-width:30ch; line-height:1.45; }
  .card .kicker { font-family:var(--mono); font-size:14px; color:var(--signal);
                  letter-spacing:2px; text-transform:uppercase; }
  .card .foot { font-family:var(--mono); font-size:15px; color:var(--faint); }
</style>
<div class="wrap">
  <div class="chrome">
    <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    <span class="title">sworn — ./scripts/demo.sh</span>
  </div>
  <pre id="t"></pre>
</div>
<div class="card" id="card">
  <div class="kicker" id="k"></div>
  <h1 id="h"></h1>
  <p id="p"></p>
  <div class="foot" id="f"></div>
</div>
<script>
  const t = document.getElementById('t');
  function cls(line) {
    if (/^\\$ /.test(line)) return 'cmd';
    if (/── PART \\d ANSWERED/.test(line)) return 'ok';
    if (/^  ok /.test(line)) return 'ok';
    if (/── /.test(line)) return 'beat';
    if (/^ {3}\\S/.test(line)) return 'beat';
    if (/\\b(bps|score|hasScore|INSUFFICIENT_DATA)\\b/.test(line)) return 'sig';
    if (/^\\s*(Ran|Suite|No files|\\[PASS\\]|Logs:)/.test(line)) return 'dim';
    return '';
  }
  window.__clear = () => { t.innerHTML = ''; };
  window.__line = (line) => {
    const s = document.createElement('span');
    const c = cls(line);
    if (c) s.className = c;
    s.textContent = line + '\\n';
    t.appendChild(s);
    // Keep the newest line in view without a visible scrollbar.
    while (t.scrollHeight > t.clientHeight && t.firstChild) t.removeChild(t.firstChild);
  };
  window.__cursor = (on) => {
    const old = document.getElementById('cur');
    if (old) old.remove();
    if (!on) return;
    const c = document.createElement('span');
    c.id = 'cur'; c.className = 'cursor';
    t.appendChild(c);
  };
  window.__card = (kicker, head, body, foot) => {
    document.getElementById('k').textContent = kicker || '';
    document.getElementById('h').textContent = head || '';
    document.getElementById('p').textContent = body || '';
    document.getElementById('f').textContent = foot || '';
    document.getElementById('card').classList.add('on');
  };
  window.__uncard = () => document.getElementById('card').classList.remove('on');
</script>`;

/** Lines worth showing. Forge prints a lot of scaffolding that says nothing on camera. */
const NOISE =
  /^(No files changed|Compiling|Solc |Compiler run|Ran \d+ test suite|Suite result|\s*$)/;

function transcript() {
  if (!existsSync(TRANSCRIPT)) {
    throw new Error(
      `no ${TRANSCRIPT}. Run: SWORN_DEMO_PAUSE=0 ./scripts/demo.sh --no-pause > docs/demo-transcript.txt 2>&1`,
    );
  }
  return readFileSync(TRANSCRIPT, 'utf8')
    .split('\n')
    .map((l) => l.replace(/\x1b\[[0-9;]*m/g, '').trimEnd());
}

/**
 * The slice of the transcript between two markers, noise removed.
 *
 * The end marker is included: every scene ends on the green `ok` line, which is the
 * beat the narration lands on. A missing marker is a hard error rather than an empty
 * scene, because the demo script's wording changes and a silently blank scene in a
 * three-minute video is the kind of thing nobody notices until it is published.
 */
function slice(lines, from, to) {
  const a = lines.findIndex((l) => l.includes(from));
  if (a < 0) throw new Error(`transcript has no line matching "${from}"`);
  const b = lines.findIndex((l, i) => i > a && l.includes(to));
  if (b < 0) throw new Error(`transcript has no line matching "${to}" after "${from}"`);
  return lines.slice(a, b + 1).filter((l) => !NOISE.test(l));
}

/**
 * Print lines one at a time, paced for a narrator rather than for a terminal.
 *
 * Lines carrying a figure dwell longer: those are the ones the voiceover lands on, and a
 * uniform delay either rushes them or drags every piece of scaffolding around them.
 */
async function type(page, lines, { perLine = 190, onNumber = 0, hold = 0 } = {}) {
  for (const line of lines) {
    await page.evaluate((l) => window.__line(l), line);
    await sleep(perLine + (/\d{3,}/.test(line) ? onNumber : 0));
  }
  if (hold) await sleep(hold);
}

async function card(page, kicker, head, body, foot, ms) {
  await page.evaluate(
    ([k, h, b, f]) => window.__card(k, h, b, f),
    [kicker, head, body, foot],
  );
  await sleep(ms);
  await page.evaluate(() => window.__uncard());
  await sleep(500);
}

/* --------------------------------------------------------------------------- site scene */

async function settle(page) {
  await page.evaluate(() => document.fonts.ready);
  await sleep(900);
}

/** Scroll to a heading and let it breathe, so the narrator can talk over it. */
async function look(page, text, ms) {
  const el = page.locator('.panel, .band', { hasText: text }).first();
  if ((await el.count()) === 0) throw new Error(`no section matching "${text}"`);
  await el.scrollIntoViewIfNeeded();
  await sleep(ms);
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  rmSync(RAW, { recursive: true, force: true });
  mkdirSync(RAW, { recursive: true });

  const lines = transcript();
  const server = spawn('npx', ['--yes', 'serve', 'app/out', '-l', String(PORT)], {
    cwd: ROOT,
    stdio: 'ignore',
  });
  const stop = () => server.kill();
  process.on('exit', stop);

  for (let i = 0; i < 40; i++) {
    try {
      if ((await fetch(`${BASE}/`)).ok) break;
    } catch {
      /* not up yet */
    }
    await sleep(500);
  }

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: SIZE,
    recordVideo: { dir: RAW, size: SIZE },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  // ---- 1. title (7s)
  await page.setContent(SHELL, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await card(
    page,
    'Sworn',
    'A hook can quote one price and charge another.',
    'A Uniswap v4 router that makes the quote and the trade the same transaction.',
    'github.com/Aman035/sworn',
    7000,
  );

  // ---- 2. where this started: 0x's post, live (16s)
  await page.goto('https://0x.org/post/uniswap-v4-hooks-were-a-mistake', {
    waitUntil: 'domcontentloaded',
    timeout: 45000,
  });
  await settle(page);
  await sleep(5500);
  await page.mouse.wheel(0, 700);
  await sleep(4500);
  await page.mouse.wheel(0, 700);
  await sleep(4500);

  // ---- 3. Hayden's reply (8s). x.com serves 403 to a headless browser, so this is a
  // still if one has been supplied, and our own attributed panel otherwise.
  const shot = process.env.HAYDEN_SHOT || resolve(OUT, 'hayden-reply.png');
  if (existsSync(shot)) {
    const b64 = readFileSync(shot).toString('base64');
    await page.setContent(
      `<!doctype html><meta charset="utf-8">
       <style>html,body{margin:0;height:100%;background:#0d1014;display:flex;
       align-items:center;justify-content:center}
       img{max-width:78%;max-height:80%;border-radius:14px;
       box-shadow:0 24px 70px rgba(0,0,0,.55)}</style>
       <img src="data:image/png;base64,${b64}">`,
      { waitUntil: 'load' },
    );
    await sleep(8000);
  } else {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await settle(page);
    await look(page, 'Uniswap v4 hooks were a mistake', 8000);
  }

  // ---- 4. our UI: the problem (34s)
  await page.setContent(SHELL, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await card(page, 'The problem', 'So we measured it.', '', '', 4200);
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await settle(page);
  await sleep(6000); // the hero counter animates on load
  await look(page, 'The event everyone indexes does not record it', 8000);
  await look(page, 'Named, on mainnet', 8000);
  await page.goto(`${BASE}/evidence/`, { waitUntil: 'networkidle' });
  await settle(page);
  await look(page, 'None of them found a single one', 6000);
  await look(page, 'Everyone is routing into them', 6000);

  // ---- 5. our UI: the solution (28s)
  await page.setContent(SHELL, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await card(page, 'The solution', 'Ask once.', '', '', 4200);
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await settle(page);
  await look(page, 'Ask once.', 10000);
  await look(page, 'Why a hook cannot tell it is being probed', 9000);

  // ---- 6. the demo, running (90s)
  await page.setContent(SHELL, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await card(
    page,
    'The demo',
    'Every figure produced by the EVM during the run.',
    'Nothing on the next screens was typed in.',
    './scripts/demo.sh',
    5200,
  );
  await page.evaluate(() => window.__clear());
  await type(page, ['$ ./scripts/demo.sh'], { perLine: 900 });
  await page.evaluate(() => window.__cursor(true));
  await sleep(700);
  await page.evaluate(() => window.__cursor(false));
  await type(page, slice(lines, 'Running DemoTest.', 'ok  a hook can lie'), {
    perLine: 620,
    onNumber: 550,
    hold: 6500,
  });

  await card(
    page,
    'And on mainnet',
    'A live Base hook, priced two ways.',
    'Same pool, same block, same swap. Two callers.',
    'test/fork/ProtectedSwap.fork.t.sol',
    5200,
  );
  await page.evaluate(() => window.__clear());
  await type(page, slice(lines, 'Sending the same swap twice', 'ok  charged'), {
    perLine: 780,
    onNumber: 700,
    hold: 8500,
  });

  // ---- 7. close (7s)
  await card(
    page,
    'Sworn',
    'Ask once.',
    'Probe every route inside the transaction that settles, and assert what executed equals what was probed.',
    'aman035.github.io/sworn',
    7000,
  );

  await context.close();
  await browser.close();
  server.kill();

  // Playwright names the file by an internal id; there is exactly one.
  const raw = readdirSync(RAW).find((f) => f.endsWith('.webm'));
  if (!raw) throw new Error('playwright produced no video');
  const webm = join(OUT, 'sworn-demo.webm');
  renameSync(join(RAW, raw), webm);
  rmSync(RAW, { recursive: true, force: true });

  const mp4 = join(OUT, 'sworn-demo.mp4');
  const ff = spawnSync(
    'ffmpeg',
    ['-y', '-i', webm, '-c:v', 'libx264', '-preset', 'slow', '-crf', '23',
     '-pix_fmt', 'yuv420p', '-movflags', '+faststart', mp4],
    { stdio: 'ignore' },
  );
  if (ff.status === 0) {
    rmSync(webm, { force: true });
    console.log(`  docs/assets/sworn-demo.mp4`);
  } else {
    console.log(`  docs/assets/sworn-demo.webm (ffmpeg unavailable, kept as webm)`);
  }
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
