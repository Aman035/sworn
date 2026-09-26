import { Band, Missing } from '@/components/Band';
import { PageHead } from '@/components/PageHead';
import { attribution, divergence, fmt, pct } from '@/lib/results';

export default function Attribution() {
  const a = attribution();
  const d = divergence();
  const products = a?.products ?? [];
  const divergentHooks = (d?.hooks ?? []).filter((h) => h.divergent).length;

  // One row per product, not per router contract. Uniswap and 0x each run more than one,
  // and splitting them made the table longer without making it say anything more.
  const byProduct = new Map<string, { into: number; total: number }>();
  for (const p of products) {
    if (p.product === 'unlabeled') continue;
    const row = byProduct.get(p.product) ?? { into: 0, total: 0 };
    row.into += p.fills_into_divergent;
    row.total += p.fills_total ?? 0;
    byProduct.set(p.product, row);
  }
  const ranked = [...byProduct.entries()]
    .filter(([, v]) => v.into > 0)
    .sort((x, y) => y[1].into - x[1].into)
    .slice(0, 6);

  const total = products.reduce((n, p) => n + p.fills_into_divergent, 0);

  return (
    <>
      <PageHead eyebrow="Attribution" title="Everyone is routing into them">
        The hooks that charge more than they quote are not somewhere off to the side. They sit on
        the main path, and the biggest routers in the ecosystem send users through them.
      </PageHead>
      <div className="sheet">
        <Band meta={a?.meta ?? null} extra={[['mapping', 'analysis/data/routers.csv']]}>
          {!a ? (
            <Missing pipeline="python -m sworn_analysis.pipelines.d_attribution" />
          ) : (
            <>
              <div className="bignum">
                <div className="bignum-n bad">{fmt(total)}</div>
                <div className="bignum-k">
                  swaps on Base went into the {divergentHooks} hooks measured as charging more than
                  they quote
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
                        {fmt(total - ranked.reduce((n, [, v]) => n + v.into, 0))}
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
                  How this is counted: every v4 swap logs the contract that called the PoolManager,
                  never the person swapping. Mapping those contracts to the products that run them
                  is what this table does, and {pct(a.unlabeled_share)} of them are contracts nobody
                  has mapped. That share is published rather than dropped.
                </p>
              </div>
            </>
          )}
        </Band>
      </div>
    </>
  );
}
