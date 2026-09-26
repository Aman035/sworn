import { Band, Missing } from '@/components/Band';
import { PageHead } from '@/components/PageHead';
import { fmt, precision, probe } from '@/lib/results';

// The result files name methods the way the pipeline does. A reader should see what the
// method actually is, and whether it is something they could run before a trade.
const METHOD: Record<string, { name: string; when: 'before' | 'after' }> = {
  static: { name: 'Static bytecode scan', when: 'before' },
  dynamic: { name: 'Differential eth_call', when: 'before' },
  trace: { name: 'Trace of a priced call', when: 'before' },
  union: { name: 'All three together', when: 'before' },
  settled_trade: { name: 'Re-quoting settled trades', when: 'after' },
};

export default function Detection() {
  const p = probe();
  const pr = precision();

  const hooks = p?.hooks ?? [];
  const traced = hooks.filter((h) => h.trace?.available);
  const onPath = traced.filter((h) => (h.trace?.env_opcodes_on_swap_path ?? []).length > 0);
  const statics = hooks.filter((h) => (h.static.env_opcodes_present ?? []).length > 0);
  const differential = hooks.filter((h) => (h.signals ?? []).includes('differential-disagreement'));

  const divergent = pr?.methods.find((m) => m.method === 'settled_trade');
  const positives = divergent ? Number(divergent.tp) + Number(divergent.fn) : 0;

  // The claim on this page is about what an integrator can run *before* a trade, so the
  // retrospective method is excluded from it.
  const upfront = (pr?.methods ?? []).filter((m) => METHOD[String(m.method)]?.when === 'before');
  const foundUpfront = upfront.reduce((n, m) => n + Number(m.tp), 0);

  return (
    <>
      <PageHead eyebrow="Detection" title="Why finding these in advance does not work">
        Static, differential and trace analysis, each scored against what hooks actually did to
        settled trades.
      </PageHead>
      <div className="sheet">
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

          <p>
            The last row is the argument for probing inside the transaction. The only method that
            catches everything is the one that runs after someone has already been hurt.
          </p>
        </Band>

        <Band meta={pr?.meta ?? null}>
          {!pr ? (
            <>
              <h2>Scored against what hooks actually did</h2>
              <Missing pipeline="python -m sworn_analysis.pipelines.f_precision" />
            </>
          ) : positives === 0 ? (
            <>
              <h2>Scored against what hooks actually did</h2>
              <div className="caveat">
                <p>
                  No hook in the scored set is labelled divergent, so precision and recall are
                  undefined here, not zero. There is nothing for a detector to be right or wrong
                  about.
                </p>
                <p>
                  The number that needs fixing is the size of the overlap between probed and
                  measured hooks, not the detectors.
                </p>
              </div>
            </>
          ) : (
            <>
              <h2>
                {foundUpfront === 0 ? `None of them found a single one` : `What each method found`}
              </h2>
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
                <p>
                  Widening the overlap is the fix, and it needs a larger re-quoted sample rather
                  than better detectors. The counts are published either way.
                </p>
              </div>
            </>
          )}
        </Band>
      </div>
    </>
  );
}
