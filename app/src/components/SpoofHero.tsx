'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * The one orchestrated moment on the site.
 *
 * A quote resolves to a number, the transaction resolves to a smaller one, and the gap
 * between them opens in the signal colour. That sequence *is* the product's argument, so
 * it gets the page's only animation and everything else stays still.
 *
 * Both figures are real: they come from `SwornRouterTest` against `GaspriceSniffHook`,
 * the same values the README and the dashboard quote.
 *
 * Nothing here is load-bearing for comprehension, with reduced motion, or before
 * hydration, the final state renders immediately.
 */
const QUOTED = 996_999_005_991_991;
const DELIVERED = 817_539_331_628_894;
const TAKEN_BPS = 1799;

const GROUP = new Intl.NumberFormat('en-US');

function useCountUp(target: number, durationMs: number, startAt: number, run: boolean) {
  const [value, setValue] = useState(run ? 0 : target);
  const frame = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!run) {
      setValue(target);
      return;
    }
    let cancelled = false;
    const begin = performance.now() + startAt;

    const tick = (now: number) => {
      if (cancelled) return;
      const t = Math.min(1, Math.max(0, (now - begin) / durationMs));
      // Ease-out cubic: the number decelerates into its final value rather than snapping,
      // which is what makes the second figure's shortfall legible.
      const eased = 1 - (1 - t) ** 3;
      setValue(Math.round(target * eased));
      if (t < 1) frame.current = requestAnimationFrame(tick);
    };

    frame.current = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [target, durationMs, startAt, run]);

  return value;
}

export function SpoofHero() {
  const [run, setRun] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduced) setRun(true);
  }, []);

  const quoted = useCountUp(QUOTED, 900, 200, run);
  const delivered = useCountUp(DELIVERED, 900, 1150, run);
  const [gapIn, setGapIn] = useState(!run);

  useEffect(() => {
    if (!run) return;
    const id = setTimeout(() => setGapIn(true), 2150);
    return () => clearTimeout(id);
  }, [run]);

  const shortfall = (DELIVERED / QUOTED) * 100;

  return (
    <div className="spoof" data-run={run ? 'yes' : 'no'}>
      <ol className="spoof-rows">
        <li>
          <span className="spoof-k">What the simulator was quoted</span>
          <span className="spoof-v">{GROUP.format(quoted)}</span>
          <span className="spoof-bar" aria-hidden="true">
            <i style={{ width: '100%' }} />
          </span>
        </li>
        <li>
          <span className="spoof-k">What the transaction delivered</span>
          <span className="spoof-v">{GROUP.format(delivered)}</span>
          <span className="spoof-bar" aria-hidden="true">
            <i className="short" style={{ width: gapIn ? `${shortfall}%` : '100%' }} />
          </span>
        </li>
      </ol>

      <div className={`spoof-gap${gapIn ? ' in' : ''}`}>
        <span className="spoof-gap-n">{(TAKEN_BPS / 100).toFixed(2)}%</span>
        <span className="spoof-gap-k">
          taken without being quoted, by a hook that reads <code>tx.gasprice</code>
        </span>
      </div>
    </div>
  );
}
