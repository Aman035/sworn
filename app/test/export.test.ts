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
 * `trailingSlash: true` emits `evidence/index.html` rather than `evidence.html`, because a plain
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

const PAGES = ['index', 'evidence'];

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

  it('the landing states the divergent-hook count against its own denominator', () => {
    // "4 of 1,404" and "4 of 25" are very different claims. The landing must not quote
    // the first one, and this is the page most likely to be screenshotted out of context.
    const d = result('divergence.json') as {
      totals: { divergent_hooks: number; eligible_hooks: number };
    };
    const html = page('index');
    expect(html).toContain(String(d.totals.divergent_hooks));
    expect(html).toContain(d.totals.eligible_hooks.toLocaleString('en-US'));
  });

  it('the landing links every named hook to a block explorer', () => {
    const d = result('divergence.json') as { hooks: { address: string; divergent: boolean }[] };
    const html = page('index');
    for (const h of d.hooks.filter((x) => x.divergent)) {
      expect(html, `landing does not link ${h.address}`).toContain(
        `https://basescan.org/address/${h.address}`,
      );
    }
  });

  it('the landing shows the real pool count', () => {
    const census = result('census.json') as { chains: { chain: string; pools_total: number }[] };
    const base = census.chains.find((c) => c.chain === 'base');
    expect(base).toBeDefined();
    expect(page('index')).toContain(base!.pools_total.toLocaleString('en-US'));
  });

  it('the evidence page states how many hooks the census found', () => {
    const census = result('census.json') as { chains: { chain: string; hooks_total: number }[] };
    const base = census.chains.find((c) => c.chain === 'base')!;
    expect(page('evidence')).toContain(base.hooks_total.toLocaleString('en-US'));
  });

  it('the evidence page names every detection method scored', () => {
    const precision = result('precision.json') as { methods: { method: string }[] };
    const html = page('evidence');
    for (const m of precision.methods) {
      expect(html, `evidence page omits ${m.method}`).toContain(m.method);
    }
  });

  it('the evidence page publishes the unlabeled attribution share', () => {
    const attribution = result('attribution.json') as { unlabeled_share: number };
    expect(attribution.unlabeled_share).toBeGreaterThan(0);
    // Assert the figure, not the wording. A coverage gap that can be dropped silently is
    // one nobody will notice missing, but the sentence around it is free to change.
    const shown = `${(attribution.unlabeled_share * 100).toFixed(1)}%`;
    expect(page('evidence'), `evidence page does not show ${shown}`).toContain(shown);
  });

  it('no page claims a hook is clean without a measurement', () => {
    // `HookBook`'s central property, mirrored in the UI: absence must never read as a
    // clean bill of health.
    const html = page('evidence');
    expect(html).toMatch(/not measured|unmeasured|insufficient/i);
  });
});
