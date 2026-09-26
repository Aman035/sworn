import { Band, Missing } from '@/components/Band';
import { PageHead } from '@/components/PageHead';
import { census, divergence, fmt, pct, probe, scores, short } from '@/lib/results';

export default function Hooks() {
  const c = census();
  const d = divergence();
  const p = probe();

  const probeBy = new Map((p?.hooks ?? []).map((h) => [h.address.toLowerCase(), h]));
  const divBy = new Map((d?.hooks ?? []).map((h) => [h.address.toLowerCase(), h]));
  const top = (c?.top_hooks ?? []).filter((h) => h.chain === 'base').slice(0, 40);
  const total = c?.chains.find((x) => x.chain === 'base')?.hooks_total;

  // Named first. The busiest-hooks table is the long tail and mostly reads "not
  // measured"; leading with it buried the four hooks the whole project is about.
  const divergent = (d?.hooks ?? [])
    .filter((h) => h.divergent)
    .sort((x, y) => (y.median_charged_excess_bps ?? 0) - (x.median_charged_excess_bps ?? 0));
  const eligible = d?.totals?.eligible_hooks ?? 0;
  const listed = new Set(
    (scores()?.hooks ?? []).filter((h) => h.flags?.includes('ALLOWLISTED')).map((h) => h.address),
  );

  return (
    <>
      <PageHead eyebrow="Hook explorer" title="The hooks that charge more than they quote">
        Measured against settled trades and named, so anyone can check them. Below the named four,
        the busiest hooks on Base — where no measurement exists, the row says so rather than reading
        as clean.
      </PageHead>
      <div className="sheet">
        {divergent.length > 0 ? (
          <Band meta={d?.meta ?? null} extra={[['threshold', 'beats its own noise floor']]}>
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
                    <th>Listed</th>
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
                          {short(h.address)}
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
                          <span className="mark on">hooklist</span>
                        ) : (
                          <span className="mark off">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="caveat">
              <p>
                &ldquo;Over-delivered&rdquo; counts fills that came out <em>better</em> than quoted.
                A hook cannot do that, so those are measurement error — and because the error is
                symmetric, their count estimates the false positives in the column beside them. A
                hook only appears here if its charged fills beat its own over-delivered tail.
              </p>
            </div>
          </Band>
        ) : null}

        <Band meta={c?.meta ?? null} extra={[['showing', 'top 40 by pool count']]}>
          {top.length === 0 ? (
            <Missing pipeline="python -m sworn_analysis.pipelines.a_census_report" />
          ) : (
            <div className="scroll">
              <table className="grid">
                <caption>
                  {fmt(top.length)} of {fmt(total)} hooks
                </caption>
                <thead>
                  <tr>
                    <th>Hook</th>
                    <th className="n">Pools</th>
                    <th>Can take</th>
                    <th>Listed</th>
                    <th>Reads environment</th>
                    <th className="n">Fills</th>
                    <th>Behaviour</th>
                  </tr>
                </thead>
                <tbody>
                  {top.map((h) => {
                    const pr = probeBy.get(h.address.toLowerCase());
                    const dv = divBy.get(h.address.toLowerCase());
                    const onPath = pr?.trace?.env_opcodes_on_swap_path ?? [];
                    const contains = pr?.static.env_opcodes_present ?? [];

                    return (
                      <tr key={h.address}>
                        <td className="addr">{short(h.address)}</td>
                        <td className="n">{fmt(h.pool_count)}</td>
                        <td>
                          <span className="mark">
                            {h.returns_delta
                              ? 'any amount'
                              : h.dynamic_fee
                                ? 'fee only'
                                : 'fixed fee'}
                          </span>
                        </td>
                        <td>
                          <span className={h.allowlisted ? 'mark on' : 'mark off'}>
                            {h.allowlisted ? 'hooklist' : 'no'}
                          </span>
                        </td>
                        <td>
                          {onPath.length > 0 ? (
                            <span className="mark bad">{onPath.join(', ')}</span>
                          ) : contains.length > 0 ? (
                            <span className="mark off">contains, never runs</span>
                          ) : pr ? (
                            <span className="mark off">no</span>
                          ) : (
                            <span className="mark off">not probed</span>
                          )}
                        </td>
                        <td className="n">
                          {dv ? fmt(dv.fills) : <span className="mark off">&mdash;</span>}
                        </td>
                        <td>
                          {!dv ? (
                            <span className="mark off">not measured</span>
                          ) : dv.divergent ? (
                            <span className="mark bad">divergent {pct(dv.charged_rate, 0)}</span>
                          ) : (
                            <span className="mark on">no excess take</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="caveat">
            <p>
              &ldquo;Contains, never runs&rdquo; means the bytecode holds an environment opcode that
              does not execute while pricing a swap. 99.2% of hooks on Base contain one, so treating
              presence as a signal would flag the entire chain.
            </p>
          </div>
        </Band>
      </div>
    </>
  );
}
