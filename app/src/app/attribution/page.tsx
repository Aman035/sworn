import { Band, Missing } from '@/components/Band';
import { PageHead } from '@/components/PageHead';
import { attribution, fmt, pct, short } from '@/lib/results';

export default function Attribution() {
  const a = attribution();
  const labelled = (a?.products ?? []).filter((p) => p.product !== 'unlabeled').slice(0, 20);

  return (
    <>
      <PageHead eyebrow="Attribution" title="Who is routing users into hooked pools">
        Swap.sender is the contract that called the PoolManager, never the user. Mapping it turns a
        fact about hooks into a question an integrator has to answer.
      </PageHead>
      <div className="sheet">
        <Band meta={a?.meta ?? null} extra={[['mapping', 'analysis/data/routers.csv']]}>
          {!a ? (
            <Missing pipeline="python -m sworn_analysis.pipelines.d_attribution" />
          ) : (
            <>
              <div className="figures">
                <div className="figure">
                  <div className="n">{fmt(a.products.length)}</div>
                  <div className="k">routers seen</div>
                </div>
                <div className="figure">
                  <div className="n grey">{pct(a.unlabeled_share)}</div>
                  <div className="k">of fills unattributed</div>
                  <div className="note">published, not hidden</div>
                </div>
              </div>

              <div className="scroll">
                <table className="grid">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Router</th>
                      <th className="n">Fills</th>
                      <th className="n">Into hooked pools</th>
                      <th>Identified by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {labelled.map((p) => (
                      <tr key={p.router}>
                        <td>{p.product}</td>
                        <td className="addr">{p.router ? short(p.router) : '—'}</td>
                        <td className="n">{fmt(p.fills_total)}</td>
                        <td className="n">{pct(p.share_of_product_v4_volume)}</td>
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
                  Half of all fills come from routers nobody has identified. That share is reported
                  rather than dropped, because an attribution table that hides its own coverage is
                  not evidence.
                </p>
              </div>
            </>
          )}
        </Band>
      </div>
    </>
  );
}
