import { Band, Missing } from '@/components/Band';
import { PageHead } from '@/components/PageHead';
import { attribution, census, divergence, fmt, pct, precision, probe } from '@/lib/results';
import { scores } from '@/lib/results';

// The result files name detection methods the way the pipeline does. A reader should see
// what the method is, and whether it is something they could run before a trade.
const METHOD: Record<string, { name: string; when: 'before' | 'after' }> = {
  static: { name: 'Static bytecode scan', when: 'before' },
  dynamic: { name: 'Differential eth_call', when: 'before' },
  trace: { name: 'Trace of a priced call', when: 'before' },
  union: { name: 'All three together', when: 'before' },
  settled_trade: { name: 'Re-quoting settled trades', when: 'after' },
};

export default function Evidence() {
  const c = census();
  const d = divergence();
  const p = probe();
  const pr = precision();
  const a = attribution();

  const divergent = (d?.hooks ?? [])
    .filter((h) => h.divergent)
    .sort((x, y) => (y.median_charged_excess_bps ?? 0) - (x.median_charged_excess_bps ?? 0));
  const eligible = d?.totals?.eligible_hooks ?? 0;
  const hooksTotal = c?.chains.find((x) => x.chain === 'base')?.hooks_total;
  const listed = new Set(
    (scores()?.hooks ?? []).filter((h) => h.flags?.includes('ALLOWLISTED')).map((h) => h.address),
  );

  const hooks = p?.hooks ?? [];
  const onPath = hooks.filter(
    (h) => h.trace?.available && (h.trace?.env_opcodes_on_swap_path ?? []).length > 0,
  );
  const statics = hooks.filter((h) => (h.static.env_opcodes_present ?? []).length > 0);
  const differential = hooks.filter((h) => (h.signals ?? []).includes('differential-disagreement'));
  const settled = pr?.methods.find((m) => m.method === 'settled_trade');
  const positives = settled ? Number(settled.tp) + Number(settled.fn) : 0;
  const foundUpfront = (pr?.methods ?? [])
    .filter((m) => METHOD[String(m.method)]?.when === 'before')
    .reduce((n, m) => n + Number(m.tp), 0);

  // One row per product, not per router contract. Uniswap and 0x each run more than one,
  // and splitting them made the table longer without making it say anything more.
  const byProduct = new Map<string, { into: number; total: number }>();
  for (const x of a?.products ?? []) {
    if (x.product === 'unlabeled') continue;
    const row = byProduct.get(x.product) ?? { into: 0, total: 0 };
    row.into += x.fills_into_divergent;
    row.total += x.fills_total ?? 0;
    byProduct.set(x.product, row);
  }
  const ranked = [...byProduct.entries()]
    .filter(([, v]) => v.into > 0)
    .sort((x, y) => y[1].into - x[1].into)
    .slice(0, 6);
  const intoDivergent = (a?.products ?? []).reduce((n, x) => n + x.fills_into_divergent, 0);

  return (
    <>
      <PageHead eyebrow="Evidence" title="Everything the measurement found">
        Named hooks, the detectors scored against them, and who routes users through them. Every
        figure is computed in this repo from a snapshot you can re-derive.
      </PageHead>
      <div className="sheet">
        <Band meta={d?.meta ?? null} extra={[['threshold', 'beats its own noise floor']]}>
          <h2>The hooks that charge more than they quote</h2>
          <p>
            A uniform random sample of Base fills, each re-quoted against the state immediately
            before it. Of the {fmt(hooksTotal)} hooks on Base, {fmt(eligible)} had enough fills to
            classify at all, and these are the ones whose charged fills beat their own measurement
            noise.
          </p>
          {divergent.length === 0 ? (
            <Missing pipeline="python -m sworn_analysis.pipelines.b_divergence" />
          ) : (
            <>
              <div className="scroll">
                <table className="grid">
                  <caption>
                    {fmt(divergent.length)} of {fmt(eligible)} hooks with enough fills to classify
                  </caption>
                  <thead>
                    <tr>
                      <th>Hook</th>
                      <th className="n">Fills</th>
                      <th className="n">Charged</th>
                      <th className="n">Over-delivered</th>
                      <th className="n">Net rate</th>
                      <th className="n">Median excess</th>
                      <th>In hooklist</th>
                    </tr>
                  </thead>
                  <tbody>
                    {divergent.map((h) => (
                      <tr key={h.address}>
                        <td className="addr">
                          <a
                            href={`https://basescan.org/address/${h.address}`}
                            rel="noreferrer noopener"
                          >
                            {h.address.slice(0, 10)}…{h.address.slice(-6)}
                          </a>
                        </td>
                        <td className="n">{fmt(h.fills)}</td>
                        <td className="n">{fmt(h.charged_fills)}</td>
                        <td className="n">{fmt(h.overdelivered_fills ?? 0)}</td>
                        <td className="n">{pct(h.net_charged_rate ?? 0, 0)}</td>
                        <td className="n bad">
                          {Math.round(h.median_charged_excess_bps ?? 0).toLocaleString('en-US')} bps
                        </td>
                        <td>
                          {listed.has(h.address) ? (
                            <span className="mark on">yes</span>
                          ) : (
                            <span className="mark off">no</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="caveat">
                <p>
                  <strong>&ldquo;Over-delivered&rdquo;</strong> counts fills that came out{' '}
                  <em>better</em> than quoted. A hook cannot do that, so those are measurement
                  error, and because the error is symmetric, their count estimates the false
                  positives in the column beside them. A hook only appears here if its charged fills
                  beat its own over-delivered tail. A hook nobody has measured is reported as
                  unmeasured, never as clean.
                </p>
                <p>
                  <strong>&ldquo;In hooklist&rdquo;</strong> means the hook is in{' '}
                  <a href="https://github.com/Uniswap/hooklist" rel="noreferrer noopener">
                    Uniswap&rsquo;s public hooklist
                  </a>{' '}
                  with verified source. Anyone can open a pull request to add theirs, it records who
                  deployed the hook and what it is permitted to do, and it says nothing about what
                  the hook charges. It is not the private allowlist Uniswap&rsquo;s routing API
                  uses, which is not published and cannot be read from here.
                </p>
              </div>
            </>
          )}
        </Band>

        <Band meta={p?.meta ?? null} extra={[['probe amount', '1e15 wei']]}>
          <h2>Three ways to ask whether a hook can spoof</h2>
          <p>
            Each looks at something different, and each fails differently. Reporting where they
            disagree is more useful than merging them into one verdict.
          </p>
          <div className="scroll">
            <table className="grid">
              <thead>
                <tr>
                  <th>Method</th>
                  <th>What it asks</th>
                  <th className="n">Flags</th>
                  <th>Blind to</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Static</td>
                  <td>Does the bytecode contain a distinguishing opcode?</td>
                  <td className="n">{fmt(statics.length)}</td>
                  <td className="dim">whether it ever runs</td>
                </tr>
                <tr>
                  <td>Differential</td>
                  <td>Does the quote move when only the environment changes?</td>
                  <td className="n">{fmt(differential.length)}</td>
                  <td className="dim">dice rolls and state-keyed behaviour</td>
                </tr>
                <tr>
                  <td>Trace</td>
                  <td>Does the hook execute one while pricing?</td>
                  <td className="n">{fmt(onPath.length)}</td>
                  <td className="dim">hooks that read state instead</td>
                </tr>
                <tr>
                  <td>Settled trades</td>
                  <td>What did users actually receive?</td>
                  <td className="n">{fmt(positives)}</td>
                  <td className="dim">nothing, but only after the fact</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Band>

        <Band meta={pr?.meta ?? null}>
          {!pr || positives === 0 ? (
            <>
              <h2>Scored against what hooks actually did</h2>
              {!pr ? (
                <Missing pipeline="python -m sworn_analysis.pipelines.f_precision" />
              ) : (
                <div className="caveat">
                  <p>
                    No hook in the scored set is labelled divergent, so precision and recall are
                    undefined here, not zero. There is nothing for a detector to be right or wrong
                    about.
                  </p>
                </div>
              )}
            </>
          ) : (
            <>
              <h2>{foundUpfront === 0 ? 'None of them found a single one' : 'What each found'}</h2>
              <p>
                {fmt(positives)} hooks in this set were independently measured, from settled trades,
                as charging more than they quote. That is the ground truth. Every method an
                integrator could run <em>before</em> a trade was scored against it.
              </p>
              <div className="scroll">
                <table className="grid">
                  <caption>of the {fmt(positives)} hooks that were charging</caption>
                  <thead>
                    <tr>
                      <th>Method</th>
                      <th>Runs</th>
                      <th className="n">Found</th>
                      <th className="n">Missed</th>
                      <th className="n">False alarms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pr.methods.map((m) => {
                      const key = String(m.method);
                      const meta = METHOD[key];
                      const after = meta?.when === 'after';
                      return (
                        <tr key={key}>
                          <td>{meta?.name ?? key}</td>
                          <td className="dim">{after ? 'after the trade' : 'before the trade'}</td>
                          <td className="n">{fmt(Number(m.tp))}</td>
                          <td className="n">{fmt(Number(m.fn))}</td>
                          <td className="n">{fmt(Number(m.fp))}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="pull">
                The only method with perfect recall is the one that reads a trade that has already
                settled. By then the user has been paid less than they were quoted.
              </p>
              <div className="caveat">
                <p>
                  <strong>{fmt(positives)} is a small ground truth.</strong> It is the overlap
                  between the hooks this repo probed and the hooks it measured from settled trades,
                  and it is too small to claim a detection <em>rate</em>. What it does show is that
                  the checks available before a trade found none of the hooks that were demonstrably
                  charging, and that the bytecode scan raised{' '}
                  {fmt(Number(pr.methods.find((m) => m.method === 'static')?.fp ?? 0))} alarms on
                  hooks that were not.
                </p>
              </div>
            </>
          )}
        </Band>

        <Band meta={a?.meta ?? null} extra={[['mapping', 'analysis/data/routers.csv']]}>
          <h2>Everyone is routing into them</h2>
          {!a ? (
            <Missing pipeline="python -m sworn_analysis.pipelines.d_attribution" />
          ) : (
            <>
              <div className="bignum">
                <div className="bignum-n bad">{fmt(intoDivergent)}</div>
                <div className="bignum-k">
                  swaps on Base went into the {divergent.length} hooks measured as charging more
                  than they quote
                </div>
              </div>

              <div className="scroll">
                <table className="grid">
                  <caption>who sent them</caption>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th className="n">Swaps into those hooks</th>
                      <th className="n">Share of its v4 swaps</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranked.map(([name, v]) => (
                      <tr key={name}>
                        <td>{name}</td>
                        <td className="n bad">{fmt(v.into)}</td>
                        <td className="n">{pct(v.into / v.total, 1)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td className="dim">routers nobody has identified</td>
                      <td className="n dim">
                        {fmt(intoDivergent - ranked.reduce((n, [, v]) => n + v.into, 0))}
                      </td>
                      <td className="n dim">{pct(a.unlabeled_share)} of all fills</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div className="caveat">
                <p>
                  <strong>This is not an accusation.</strong> These products are doing the normal
                  thing, which is to trust a quote. That is the whole point: the gap is invisible
                  from where a router stands, so avoiding it cannot be a matter of diligence.
                </p>
                <p>
                  Every v4 swap logs the contract that called the PoolManager, never the person
                  swapping. Mapping those contracts to the products that run them is what this table
                  does, and {pct(a.unlabeled_share)} of them are contracts nobody has mapped. That
                  share is published rather than dropped.
                </p>
              </div>
            </>
          )}
        </Band>
      </div>
    </>
  );
}
