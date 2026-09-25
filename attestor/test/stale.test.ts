import { describe, expect, it } from 'vitest';

import { STALE_UPDATE_SELECTOR, isStaleUpdate } from '../src/index.js';

/**
 * `HookBook` refuses a write that is not newer than what it holds. That is the right
 * contract behaviour and the wrong thing for an hourly job to treat as a failure: the
 * analysis it publishes moves far more slowly than the schedule, so *most* runs have
 * nothing newer to say. A job that exits non-zero on the expected case is a job nobody
 * keeps enabled.
 */
describe('stale update detection', () => {
  it('recognises the revert by selector', () => {
    const error = new Error(
      `The contract function "setScores" reverted.\n\nError: ${STALE_UPDATE_SELECTOR}`,
    );
    expect(isStaleUpdate(error)).toBe(true);
  });

  it('recognises the revert by name', () => {
    expect(isStaleUpdate(new Error('reverted with StaleUpdate(51778292, 51778292)'))).toBe(true);
  });

  it('does not swallow other reverts', () => {
    // NotAttestor, ScoreTooHigh and a plain transport failure must all still propagate:
    // silently continuing past those would publish nothing and report success.
    expect(isStaleUpdate(new Error('reverted: NotAttestor()'))).toBe(false);
    expect(isStaleUpdate(new Error('0xdde328f8'))).toBe(false);
    expect(isStaleUpdate(new Error('connect ECONNREFUSED'))).toBe(false);
  });

  it('handles a non-Error rejection', () => {
    expect(isStaleUpdate('boom')).toBe(false);
    expect(isStaleUpdate(undefined)).toBe(false);
  });
});
