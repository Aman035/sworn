import { Band, Missing } from '@/components/Band';
import { PageHead } from '@/components/PageHead';
import { fmt, precision, probe } from '@/lib/results';

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
                  <td className="dim">nothing — but only after the fact</td>
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
          <h2>Precision against settled trades</h2>
          {!pr ? (
            <Missing pipeline="python -m sworn_analysis.pipelines.f_precision" />
          ) : positives === 0 ? (
            <div className="caveat">
              <p>
                No hook in the scored set is labelled divergent, so precision and recall are
                undefined here — not zero. There is nothing for a detector to be right or wrong
                about.
              </p>
              <p>
                The number that needs fixing is the size of the overlap between probed and measured
                hooks, not the detectors.
              </p>
            </div>
          ) : (
            <div className="scroll">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Method</th>
                    <th className="n">TP</th>
                    <th className="n">FP</th>
                    <th className="n">FN</th>
                    <th className="n">Precision</th>
                    <th className="n">Recall</th>
                  </tr>
                </thead>
                <tbody>
                  {pr.methods.map((m) => (
                    <tr key={String(m.method)}>
                      <td>{String(m.method)}</td>
                      <td className="n">{fmt(Number(m.tp))}</td>
                      <td className="n">{fmt(Number(m.fp))}</td>
                      <td className="n">{fmt(Number(m.fn))}</td>
                      <td className="n">{Number(m.precision).toFixed(2)}</td>
                      <td className="n">{Number(m.recall).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Band>
      </div>
    </>
  );
}
