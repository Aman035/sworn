import { Band, Missing } from '@/components/Band';
import { PageHead } from '@/components/PageHead';
import { census, divergence, fmt, pct, probe, short } from '@/lib/results';

export default function Hooks() {
  const c = census();
  const d = divergence();
  const p = probe();

  const probeBy = new Map((p?.hooks ?? []).map((h) => [h.address.toLowerCase(), h]));
  const divBy = new Map((d?.hooks ?? []).map((h) => [h.address.toLowerCase(), h]));
  const top = (c?.top_hooks ?? []).filter((h) => h.chain === 'base').slice(0, 40);
  const total = c?.chains.find((x) => x.chain === 'base')?.hooks_total;

  return (
    <>
      <PageHead eyebrow="Hook explorer" title="Every hook on Base, and what it does">
        Sorted by how many pools route through them. A hook with no measurement reads as unmeasured,
        never as clean.
      </PageHead>
      <div className="sheet">
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
