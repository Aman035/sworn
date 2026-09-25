import { describe, expect, it } from 'vitest';
import { SWORN_CHAINS, chainIdFor } from '../src/index.js';

describe('chain map', () => {
  it('matches analysis/config.yaml chain ids', () => {
    expect(chainIdFor('base')).toBe(8453);
    expect(chainIdFor('bnb')).toBe(56);
    expect(chainIdFor('unichain')).toBe(130);
  });

  it('has no duplicate chain ids', () => {
    const ids = Object.values(SWORN_CHAINS);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
