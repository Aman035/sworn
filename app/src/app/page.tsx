import { Band } from '@/components/Band';
import { attribution, census, divergence, fmt, pct, probe, replay } from '@/lib/results';

export default function Overview() {
  const c = census();
  const d = divergence();
  const p = probe();
  const a = attribution();
  const r = replay();

  const base = c?.chains.find((x) => x.chain === 'base');
  const hookedShare = base ? base.hooked_pools / base.pools_total : null;

  const probed = p?.hooks ?? [];
  const staticFlag = probed.filter((h) => (h.static.env_opcodes_present ?? []).length > 0).length;
  const onPath = probed.filter((h) => (h.trace?.env_opcodes_on_swap_path ?? []).length > 0).length;

  return (
    <div className="sheet">
      {/* The gap between quoted and delivered is the product. It leads. */}
      <Band
        meta={null}
        extra={[
          ['measured by', 'SwornRouterTest'],
          ['fixture', 'GaspriceSniffHook'],
        ]}
      >
        <h2>A hook can quote one price and deliver another</h2>
        <p>
          The same swap, through a hook that charges only when the gas price is non-zero. A
          simulator sees the first number. A user gets the second.
        </p>

        <div className="gap-figure">
          <div className="gap-row">
            <span className="what">Quoted to a simulator</span>
            <span className="amount">996,999,005,991,991</span>
          </div>
          <div className="gap-row">
            <span className="what">Delivered to a real transaction</span>
            <span className="amount">817,539,331,628,894</span>
          </div>
          <div className="gap-row delta">
            <span className="what">Taken without being quoted</span>
            <span className="amount">17.99%</span>
          </div>
          <div className="gap-row delta recovered">
            <span className="what">Recovered when routed through Sworn</span>
            <span className="amount">21.95%</span>
          </div>
        </div>

        <p>
          Sworn probes every candidate route inside the transaction that executes, then asserts the
          executed amount equals the probed one. There is no separate quote for a hook to lie to.
        </p>
      </Band>

      {r ? (
        <Band meta={r.meta}>
          <h2>What the guarantee is worth, and what it costs</h2>
          <p>
            For every measured fill, every other pool that could have filled the same trade was
            quoted against the same pre-fill state. Probing costs a fixed amount of gas and saves a
            proportion of the trade, so it pays above a trade size and not below it.
          </p>

          <div className="figures">
            <div className="figure">
              <div className="n">${(r.totals.breakeven_notional_usd ?? 0).toFixed(2)}</div>
              <div className="k">break-even trade size</div>
              <div className="note">below this, probe gas exceeds the expected saving</div>
            </div>
            <div className="figure">
              <div className="n">{(r.totals.median_protection_bps ?? 0).toFixed(0)} bps</div>
              <div className="k">median protection when a better route existed</div>
            </div>
            <div className="figure">
              <div className="n grey">{pct(r.totals.protection_hit_rate)}</div>
              <div className="k">of fills with an alternative had a better one</div>
              <div className="note">{fmt(r.totals.fills_protected)} of {fmt(r.totals.fills_with_alternatives)}</div>
            </div>
            <div className="figure">
              <div className="n grey">${(r.totals.probe_gas_usd_median ?? 0).toFixed(4)}</div>
              <div className="k">median cost to protect one trade</div>
            </div>
          </div>

          <div className="caveat">
            <p>
              Only {pct(r.totals.price_confidence)} of these fills pay out in a token this repo can
              value from the chain, and {fmt(r.totals.implausible_fills)} candidate routes quoting
              implausible multiples were excluded as mispriced dust rather than counted as recovered
              value. Both are published so the dollar figures can be discounted accordingly.
            </p>
          </div>
        </Band>
      ) : null}

      <Band meta={c?.meta ?? null}>
        <h2>What is out there</h2>
        <p>
          Every v4 pool on Base, from the PoolManager deployment block to the snapshot head. An
          independent second implementation reconciles this count to 0.00%.
        </p>
        <div className="figures">
          <div className="figure">
            <div className="n">{fmt(base?.pools_total)}</div>
            <div className="k">pools on Base</div>
          </div>
          <div className="figure">
            <div className="n brass">{pct(hookedShare)}</div>
            <div className="k">carry a hook</div>
            <div className="note">{fmt(base?.hooked_pools)} pools</div>
          </div>
          <div className="figure">
            <div className="n">{fmt(base?.hooks_total)}</div>
            <div className="k">distinct hooks</div>
          </div>
          <div className="figure">
            <div className="n">{fmt(base?.upgradeable)}</div>
            <div className="k">upgradeable</div>
            <div className="note">today&rsquo;s bytecode is not tomorrow&rsquo;s</div>
          </div>
        </div>
      </Band>

      <Band meta={p?.meta ?? null}>
        <h2>Containing an opcode is not reading one</h2>
        <p>
          Almost every hook contains an instruction that could distinguish a simulation. Very few
          execute one while pricing a swap. That gap is what makes a detector useful or useless.
        </p>
        <div className="funnel">
          <Rung
            label="Contain any environment opcode"
            count="68,665 of 69,242"
            width={99.2}
            why="solc emits GAS for every external call, so this flags the whole chain and says nothing."
          />
          <Rung
            label="Contain a simulation-distinguishing opcode"
            count="26,525 of 69,242"
            width={38.3}
            why="tx.origin appears in 35.4% of hooks; tx.gasprice, the textbook signal, in 0.3%."
          />
          <Rung
            label="Execute one while pricing a swap"
            count={`${onPath} of ${probed.length} traced`}
            width={probed.length ? (onPath / probed.length) * 100 : 0}
            why="Established by tracing the call and attributing each opcode to the contract that ran it."
            narrow
          />
        </div>
        <p>
          Of the {staticFlag} hooks flagged statically in this sample, {onPath} actually reads the
          environment on the swap path.
        </p>
      </Band>

      <Band meta={d?.meta ?? null}>
        <h2>What settled trades show</h2>
        {d ? (
          <>
            <div className="figures">
              <div className="figure">
                <div className="n">{fmt(d.totals.fills)}</div>
                <div className="k">fills re-quoted</div>
              </div>
              <div className="figure">
                <div className="n">{fmt(d.totals.hooks)}</div>
                <div className="k">hooks measured</div>
              </div>
              <div className="figure">
                <div className="n grey">{fmt(d.totals.divergent_hooks)}</div>
                <div className="k">divergent hooks</div>
                <div className="note">at every threshold swept</div>
              </div>
              <div className="figure">
                <div className="n">{pct(a?.unlabeled_share, 1)}</div>
                <div className="k">of fills unattributed</div>
                <div className="note">published, not hidden</div>
              </div>
            </div>
            <div className="caveat">
              <p>
                This sample is drawn from the busiest hooks by fill count, which on Base are largely
                allowlisted infrastructure. It answers a different question than a uniform sample.
              </p>
              <p>
                Every hooked re-quote used empty hookData, because recovering what a router passed
                needs a per-router decoder. Until that exists these figures support the machinery,
                not a claim about how often hooks charge.
              </p>
            </div>
          </>
        ) : null}
      </Band>
    </div>
  );
}

function Rung({
  label,
  count,
  width,
  why,
  narrow,
}: {
  label: string;
  count: string;
  width: number;
  why: string;
  narrow?: boolean;
}) {
  return (
    <div className={narrow ? 'rung narrow' : 'rung'}>
      <div className="head">
        <span className="label">{label}</span>
        <span className="count">{count}</span>
      </div>
      <div className="track">
        <i style={{ width: `${Math.max(width, 0.6)}%` }} />
      </div>
      <p className="why">{why}</p>
    </div>
  );
}
