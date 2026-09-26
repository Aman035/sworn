import type { Meta } from '@/lib/results';

/**
 * Where the numbers above came from, in a sentence.
 *
 * Every figure on this site is computed by a pipeline in the repo from a snapshot with a
 * recorded sha256, and saying so is the point of the whole project. Saying so by printing
 * four hashes, two block ranges and a git sha above the content was not: a reader met a
 * wall of hex before they met the argument.
 *
 * So the claim is now one plain line underneath the section, and the hashes anyone would
 * actually verify against live behind a disclosure.
 */
function group(n: number): string {
  return n.toLocaleString('en-US');
}

export function Rail({
  meta,
  extra,
}: {
  meta: Meta | null;
  extra?: [string, string][] | undefined;
}) {
  if (!meta) {
    if (!extra?.length) return null;
    return <p className="source">{extra.map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>;
  }

  const snaps = meta.snapshots ?? [];
  const ranged = snaps.filter((s) => s.block_from && s.block_to);
  const from = ranged.length ? Math.min(...ranged.map((s) => s.block_from as number)) : null;
  const to = ranged.length ? Math.max(...ranged.map((s) => s.block_to as number)) : null;
  const rows = snaps.reduce((n, s) => n + (s.rows ?? 0), 0);

  return (
    <details className="source">
      <summary>
        Measured from
        {from && to ? ` Base blocks ${group(from)} to ${group(to)}` : ' a pinned snapshot'}
        {rows ? `, ${group(rows)} indexed rows` : ''}. Computed in this repo, from data you can
        re-derive.
      </summary>
      <dl>
        {snaps.map((s) => (
          <div key={s.name}>
            <dt>{s.name}</dt>
            <dd>
              <span className="hash">{s.sha256.slice(0, 16)}…</span>
              {s.rows ? ` · ${group(s.rows)} rows` : ''}
              {s.block_from && s.block_to
                ? ` · blocks ${group(s.block_from)}–${group(s.block_to)}`
                : ''}
            </dd>
          </div>
        ))}
        <div>
          <dt>built at</dt>
          <dd>{meta.script_commit}</dd>
        </div>
        {extra?.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
