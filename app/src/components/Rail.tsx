import type { Meta } from '@/lib/results';

/**
 * The provenance rail.
 *
 * Every figure on this page came from a pipeline reading a hashed snapshot. Putting that
 * origin beside the numbers, rather than in a footnote, is the point: a reader can fetch
 * the same snapshot and re-derive the figure instead of taking it on trust.
 */
/** Snapshots shown before the rail summarises the rest. Beyond this the rail grows taller
 *  than the figures it annotates, which inverts the hierarchy it exists to support. */
const SHOWN = 2;

export function Rail({
  meta,
  extra,
}: {
  meta: Meta | null;
  extra?: [string, string][] | undefined;
}) {
  // A band with no snapshot is not necessarily a band with no provenance: the lead figure
  // comes from a contract test, which has a source worth naming. Discarding `extra` here
  // made a sourced panel read as an empty one.
  if (!meta) {
    return (
      <dl className="rail">
        {extra?.length ? (
          extra.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))
        ) : (
          <div>
            <dt>Source</dt>
            <dd>not yet computed</dd>
          </div>
        )}
      </dl>
    );
  }

  return (
    <dl className="rail">
      {meta.snapshots.slice(0, SHOWN).map((s) => (
        <div key={s.name}>
          <dt>{s.name}</dt>
          <dd>
            <span className="hash">{s.sha256.slice(0, 16)}…</span>
            {s.block_from !== undefined && s.block_to !== undefined && s.block_to > 0 ? (
              <>
                <br />
                <span className="range">
                  blocks {s.block_from.toLocaleString('en-US')}&ndash;
                  {s.block_to.toLocaleString('en-US')}
                </span>
              </>
            ) : null}
            {s.rows ? (
              <>
                <br />
                {s.rows.toLocaleString('en-US')} rows
              </>
            ) : null}
          </dd>
        </div>
      ))}
      {meta.snapshots.length > SHOWN ? (
        <div>
          <dt>and {meta.snapshots.length - SHOWN} more</dt>
          {/* A comma list of names, not a hash: `.hash` is nowrap so a hex string stays
              intact, and reusing it here pushed the page 16px wide at 375px. */}
          <dd className="more">
            {meta.snapshots
              .slice(SHOWN)
              .map((s) => s.name)
              .join(', ')}
          </dd>
        </div>
      ) : null}
      <div>
        <dt>Built at</dt>
        <dd>{meta.script_commit}</dd>
      </div>
      {extra?.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
