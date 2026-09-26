import Link from 'next/link';

import { Reveal } from '@/components/Reveal';
import { SpoofHero } from '@/components/SpoofHero';
import { census, divergence, fmt, pct, precision, replay, scores } from '@/lib/results';

export default function Landing() {
  const c = census();
  const d = divergence();
  const r = replay();
  const pr = precision();
  // The hooklist flag lives on the score row, not the divergence row: whether a hook is
  // allowlisted is an attribute of the hook, not of this measurement.
  const listed = new Set(
    (scores()?.hooks ?? []).filter((h) => h.flags?.includes('ALLOWLISTED')).map((h) => h.address),
  );

  const base = c?.chains.find((x) => x.chain === 'base');
  const divergent = (d?.hooks ?? []).filter((h) => h.divergent);
  const settled = pr?.methods.find((m) => m.method === 'settled_trade');
  const blind = (pr?.methods ?? []).filter((m) => m.method !== 'settled_trade');
  const allBlind = blind.length > 0 && blind.every((m) => Number(m.recall) === 0);

  return (
    <div className="landing">
      <section className="hero">
        <div className="hero-inner">
          <p className="hero-eyebrow">Execution integrity for Uniswap&nbsp;v4</p>
          <h1 className="hero-h">
            A hook can quote one price
            <br />
            and charge another.
          </h1>
          <p className="hero-sub">
            The quote comes from <code>eth_call</code>. The charge happens in a transaction. A hook
            is arbitrary code that runs in both — and can tell them apart.
          </p>

          <SpoofHero />

          <div className="hero-cta">
            <Link className="btn" href="/hooks">
              See what hooks actually do
            </Link>
            <a
              className="btn ghost"
              href="https://github.com/Aman035/sworn"
              rel="noreferrer noopener"
            >
              Read the measurements
            </a>
          </div>
        </div>
      </section>

      {/* The origin, attributed. 0x's study establishes the scale of the problem; this
          repo cannot, and presenting their figures as ours would undo the one thing it
          has going for it. Every cited number carries its source inline. */}
      <Reveal as="section" className="panel origin">
        <div className="panel-inner">
          <div className="origin-grid">
            <article>
              <p className="origin-who">
                <a
                  href="https://0x.org/post/uniswap-v4-hooks-were-a-mistake"
                  rel="noreferrer noopener"
                >
                  0x, 14 September 2026
                </a>
              </p>
              <h2>&ldquo;Uniswap v4 hooks were a mistake&rdquo;</h2>
              <ul className="origin-stats">
                <li>
                  <b>84,163</b> hooks analysed, six chains
                </li>
                <li>
                  <b className="bad">54.2%</b> malicious
                </li>
                <li>
                  <b>19.4%</b> safe
                </li>
              </ul>
              <p className="origin-named">
                They named one:{' '}
                <a
                  href="https://basescan.org/address/0x800cef53c3fd41109dffec62e5251bdd7acba5c7"
                  rel="noreferrer noopener"
                >
                  <code>0x800cef53…</code>
                </a>{' '}
                on Base, an ETH/NVDAc pool — a median fee of <b>18%</b> when it charged, and{' '}
                <b className="bad">$143,037</b> taken.
              </p>
              <p className="fineprint">
                Their analysis, their numbers — cited, not reproduced here.
              </p>
            </article>

            <article>
              <p className="origin-who">
                <a
                  href="https://x.com/haydenzadams/status/2099711270115013085"
                  rel="noreferrer noopener"
                >
                  Hayden Adams, in reply
                </a>
              </p>
              <blockquote>Skill issue, don&rsquo;t route to bad hooks</blockquote>
              <p>
                Pointing integrators at the Uniswap API, which &ldquo;avoids malicious hooks&rdquo;.
                He is right — and this repo is an attempt to make that advice executable, because it
                leaves open the question an integrator actually faces:{' '}
                <strong>how do you know which ones are bad, at the moment you route?</strong>
              </p>
            </article>
          </div>
        </div>
      </Reveal>

      <Reveal as="section" className="strip">
        <div className="strip-inner">
          {base ? (
            <div className="strip-fig">
              <b>{fmt(base.pools_total)}</b>
              <span>v4 pools indexed on Base</span>
            </div>
          ) : null}
          {base ? (
            <div className="strip-fig">
              <b>{pct(base.hooked_pools / base.pools_total, 1)}</b>
              <span>of them carry a hook</span>
            </div>
          ) : null}
          {d ? (
            <div className="strip-fig">
              <b className="bad">{fmt(d.totals.divergent_hooks)}</b>
              <span>
                of {fmt(d.totals.eligible_hooks)} measurable hooks charge more than they quote
              </span>
            </div>
          ) : null}
          {r?.totals.breakeven_notional_usd ? (
            <div className="strip-fig">
              <b>${r.totals.breakeven_notional_usd.toFixed(2)}</b>
              <span>trade size above which verifying pays for itself</span>
            </div>
          ) : null}
        </div>
      </Reveal>

      <Reveal as="section" className="panel">
        <div className="panel-inner">
          <h2>The event everyone indexes does not record it</h2>
          <p>
            <code>PoolManager</code> emits <code>Swap</code> between <code>beforeSwap</code> and{' '}
            <code>afterSwap</code>, so its amounts exclude whatever the hook takes in{' '}
            <code>afterSwap</code>. Measured on Base, for a hook taking exactly one percent:
          </p>
          <dl className="ledger">
            <div>
              <dt>
                <code>Swap</code> event
              </dt>
              <dd>3,941,355,102,139,778,949</dd>
            </div>
            <div>
              <dt>
                <code>swap()</code> return value
              </dt>
              <dd>3,901,941,551,118,381,160</dd>
            </div>
            <div className="delta">
              <dt>difference</dt>
              <dd>39,413,551,021,397,789 — exactly one percent</dd>
            </div>
          </dl>
          <p>
            Read from the event, that hook appears to hand users an extra percent. It charges them.
            Any analytics built on <code>Swap</code> events under-reports exactly the hooks that
            take the most.
          </p>
        </div>
      </Reveal>

      {divergent.length > 0 ? (
        <Reveal as="section" className="panel">
          <div className="panel-inner">
            <h2>Named, on mainnet</h2>
            <p>
              A uniform random sample of Base fills, each re-quoted against the state immediately
              before it. These are the hooks that survived their own measurement noise.
            </p>
            <div className="scroll">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Hook</th>
                    <th className="n">Fills</th>
                    <th className="n">Net charged</th>
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
                          {h.address.slice(0, 10)}…{h.address.slice(-6)}
                        </a>
                      </td>
                      <td className="n">{fmt(h.fills)}</td>
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
            <p className="fineprint">
              Roughly half of all charged fills in this sample are measurement error, quantified and
              published beside the result rather than left for a reader to find.
            </p>
          </div>
        </Reveal>
      ) : null}

      {allBlind && settled ? (
        <Reveal as="section" className="panel">
          <div className="panel-inner">
            <h2>Detection does not catch it</h2>
            <p>
              Static bytecode analysis, differential <code>eth_call</code>, and{' '}
              <code>debug_traceCall</code> were each scored against what hooks actually did to
              settled trades. Every one of them scored zero recall. Only re-quoting settled trades
              caught anything — and that works after someone has already been paid less than they
              were quoted.
            </p>
            <p className="pull">
              A score tells you what a hook did last week. It cannot tell you what it is doing to
              your transaction right now.
            </p>
          </div>
        </Reveal>
      ) : null}

      <Reveal as="section" className="panel solution">
        <div className="panel-inner">
          <h2>So stop quoting. Probe.</h2>
          <p>
            <code>SwornRouter</code> moves the quote inside the transaction that settles it. Every
            candidate route is executed for real and then reverted, the best is taken, and the
            router asserts that what executed equals what it probed.
          </p>
          <ol className="steps">
            <li>
              <b>unlock</b>
              <span>PoolManager hands control back to the router</span>
            </li>
            <li>
              <b>probe</b>
              <span>
                run each candidate for real, then revert — state and transient storage roll back
              </span>
            </li>
            <li>
              <b>select</b>
              <span>keep the best probed delta and the route that produced it</span>
            </li>
            <li>
              <b>execute</b>
              <span>run that route through the same entry point</span>
            </li>
            <li className="assert">
              <b>assert</b>
              <span>executedDelta == probed[chosen], or the whole transaction reverts</span>
            </li>
          </ol>
          <p>
            The probe sees the same <code>tx.gasprice</code>, the same <code>tx.origin</code>, the
            same everything a hook could key on, because it <em>is</em> the real environment. There
            is no separate quote left to lie to.
          </p>
        </div>
      </Reveal>

      {r ? (
        <Reveal as="section" className="panel">
          <div className="panel-inner">
            <h2>What the guarantee is worth</h2>
            <p>
              For every measured fill, every other pool that could have filled the same trade was
              quoted against the same pre-fill state. Probing costs a fixed amount of gas and saves
              a proportion of the trade, so it pays above a trade size and not below it.
            </p>
            <div className="figures">
              <div className="figure">
                <div className="n">${(r.totals.breakeven_notional_usd ?? 0).toFixed(2)}</div>
                <div className="k">break-even trade size</div>
                <div className="note">below this, probe gas exceeds the expected saving</div>
              </div>
              <div className="figure">
                <div className="n">{(r.totals.median_protection_bps ?? 0).toFixed(0)} bps</div>
                <div className="k">median protection where a better route existed</div>
              </div>
              <div className="figure">
                <div className="n grey">{pct(r.totals.protection_hit_rate)}</div>
                <div className="k">of fills with an alternative had a better one</div>
                <div className="note">
                  {fmt(r.totals.fills_protected)} of {fmt(r.totals.fills_with_alternatives)}
                </div>
              </div>
              <div className="figure">
                <div className="n grey">${(r.totals.probe_gas_usd_median ?? 0).toFixed(4)}</div>
                <div className="k">median cost to protect one trade</div>
              </div>
            </div>
            <div className="caveat">
              <p>
                Only {pct(r.totals.price_confidence)} of these fills pay out in a token this repo
                can value from the chain, and {fmt(r.totals.implausible_fills)} candidate routes
                quoting implausible multiples were excluded as mispriced dust rather than counted as
                recovered value. Both are published so the dollar figures can be discounted
                accordingly.
              </p>
            </div>
            <div className="hero-cta">
              <Link className="btn" href="/hooks">
                Browse the evidence
              </Link>
            </div>
          </div>
        </Reveal>
      ) : null}
    </div>
  );
}
