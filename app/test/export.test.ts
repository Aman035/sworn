import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Smoke tests against the built static export.
 *
 * The plan called for Playwright. The export is fully static — every figure is baked into
 * the HTML at build time — so a browser would only confirm that Chrome can display a
 * string that is already in the file. Reading the file asserts the same thing, runs in
 * milliseconds, and cannot flake. What a browser *would* add is layout and interaction,
 * which is covered by the responsive work in `globals.css` and by hand.
 *
 * What these guard is the failure this dashboard is actually prone to: a result file
 * changing shape and every figure silently rendering as `undefined`, `NaN` or an empty
 * string while the page still looks fine.
 */

const ROOT = resolve(__dirname, '..', '..');
const OUT = resolve(ROOT, 'app', 'out');

/**
 * `trailingSlash: true` emits `hooks/index.html` rather than `hooks.html`, because a plain
 * static host (GitHub Pages) does no extensionless-path rewriting. Both shapes are accepted
 * so these tests describe the pages rather than the current export setting.
 */
function page(name: string): string {
  const stem = name.replace(/\.html$/, '');
  for (const candidate of [`${stem}.html`, `${stem}/index.html`, name]) {
    const path = resolve(OUT, candidate);
    if (existsSync(path)) return readFileSync(path, 'utf8');
  }
  throw new Error(`${name} missing — run \`npm run build\` in app/ first`);
}

function result(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(ROOT, 'data', 'results', name), 'utf8'));
}

const PAGES = ['index', 'hooks', 'detection', 'attribution'];

describe('static export', () => {
  it.each(PAGES)('%s is built', (name) => {
    expect(page(name).length).toBeGreaterThan(1000);
  });

  it.each(PAGES)('%s renders no placeholder values', (name) => {
    const html = page(name);
    // A result file that changed shape shows up here and nowhere else: the layout still
    // looks right, the numbers are just gone.
    for (const bad of ['NaN', 'undefined', 'Infinity', '[object Object]']) {
      expect(html, `${name} contains ${bad}`).not.toContain(`>${bad}<`);
    }
  });

  it.each(PAGES)('%s carries its provenance', (name) => {
    // Every panel states the snapshot it came from; a page without one is a page making
    // unsourced claims, which is the thing this repo exists to avoid.
    expect(page(name)).toMatch(/blocks\s|snapshot|rows/i);
  });

  it('the overview shows the real pool count', () => {
    const census = result('census.json') as { chains: { chain: string; pools_total: number }[] };
    const base = census.chains.find((c) => c.chain === 'base');
    expect(base).toBeDefined();
    expect(page('index')).toContain(base!.pools_total.toLocaleString('en-US'));
  });

  it('the hook explorer lists the hooks the census found', () => {
    const census = result('census.json') as { chains: { chain: string; hooks_total: number }[] };
    const base = census.chains.find((c) => c.chain === 'base')!;
    expect(page('hooks')).toContain(base.hooks_total.toLocaleString('en-US'));
  });

  it('the detection page names every method scored', () => {
    const precision = result('precision.json') as { methods: { method: string }[] };
    const html = page('detection');
    for (const m of precision.methods) {
      expect(html, `detection page omits ${m.method}`).toContain(m.method);
    }
  });

  it('the attribution page publishes its unlabeled share', () => {
    const attribution = result('attribution.json') as { unlabeled_share: number };
    // The number matters less than its presence: a coverage figure that can be dropped
    // silently is a coverage figure nobody will notice missing.
    expect(attribution.unlabeled_share).toBeGreaterThan(0);
    expect(page('attribution')).toMatch(/unattributed|unlabel/i);
  });

  it('no page claims a hook is clean without a measurement', () => {
    // `HookBook`'s central property, mirrored in the UI: absence must never read as a
    // clean bill of health.
    const html = page('hooks');
    expect(html).toMatch(/not measured|unmeasured|insufficient/i);
  });
});
