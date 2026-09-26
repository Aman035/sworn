import { Band, Missing } from '@/components/Band';
import { PageHead } from '@/components/PageHead';
import { attribution, fmt, pct, short } from '@/lib/results';

export default function Attribution() {
  const a = attribution();
  const products = a?.products ?? [];

  // The column that matters is fills into hooks *measured as charging more than they
  // quote*. "Into hooked pools" is close to meaningless on Base, where 98.5% of pools
  // carry a hook — showing it beside a named company implied a harm the data did not.
  const labelled = products
    .filter((p) => p.product !== 'unlabeled')
    .sort((x, y) => y.fills_into_divergent - x.fills_into_divergent)
    .slice(0, 12);

  const intoDivergent = products.reduce((n, p) => n + p.fills_into_divergent, 0);
  const totalFills = products.reduce((n, p) => n + (p.fills_total ?? 0), 0);

  return (
    <>
      <PageHead eyebrow="Attribution" title="Who is routing users into these hooks">
        Every major router does. <code>Swap.sender</code> is the contract that called the
        PoolManager, never the user, so mapping it turns a fact about hooks into a question an
        integrator has to answer.
      </PageHead>
      <div className="sheet">
        <Band meta={a?.meta ?? null} extra={[['mapping', 'analysis/data/routers.csv']]}>
          {!a ? (
            <Missing pipeline="python -m sworn_analysis.pipelines.d_attribution" />
          ) : (
            <>
              <div className="figures">
                <div className="figure">
                  <div className="n bad">{fmt(intoDivergent)}</div>
                  <div className="k">fills routed into hooks that charge more than they quote</div>
                  <div className="note">
                    {pct(intoDivergent / totalFills)} of all fills measured
                  </div>
                </div>
                <div className="figure">
                  <div className="n">{fmt(products.length)}</div>
                  <div className="k">distinct routers seen</div>
                </div>
                <div className="figure">
                  <div className="n grey">{pct(a.unlabeled_share)}</div>
                  <div className="k">of fills unattributed</div>
                  <div className="note">published, not hidden</div>
                </div>
              </div>

              <div className="scroll">
                <table className="grid">
                  <caption>
                    top {labelled.length} identified routers, by fills into divergent hooks
                  </caption>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Router</th>
                      <th className="n">Fills</th>
                      <th className="n">Into divergent hooks</th>
                      <th>Identified by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {labelled.map((p) => (
                      <tr key={p.router}>
                        <td>{p.product}</td>
                        <td className="addr">{p.router ? short(p.router) : '—'}</td>
                        <td className="n">{fmt(p.fills_total)}</td>
                        <td className={p.fills_into_divergent > 0 ? 'n bad' : 'n'}>
                          {p.fills_into_divergent > 0 ? fmt(p.fills_into_divergent) : '—'}
                        </td>
                        <td>
                          <span className={p.confidence >= 1 ? 'mark on' : 'mark'}>
                            {p.confidence >= 1 ? 'verified source' : `confidence ${p.confidence}`}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="caveat">
                <p>
                  <strong>This is not an accusation.</strong> These products are doing the normal
                  thing, which is to trust a quote. That is the point: the gap is invisible from
                  where a router stands, so routing around it cannot be a matter of diligence.
                </p>
                <p>
                  {pct(a.unlabeled_share)} of fills come from routers nobody has identified, and
                  that share is reported rather than dropped — an attribution table that hides its
                  own coverage is not evidence.
                </p>
              </div>
            </>
          )}
        </Band>
      </div>
    </>
  );
}
