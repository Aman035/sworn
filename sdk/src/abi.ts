/** Minimal ABIs for the two contracts the SDK touches. */

export const swornRouterAbi = [
  {
    type: 'function',
    name: 'swornSwap',
    stateMutability: 'payable',
    inputs: [
      {
        name: 'cands',
        type: 'tuple[]',
        components: [
          {
            name: 'hops',
            type: 'tuple[]',
            components: [
              {
                name: 'key',
                type: 'tuple',
                components: [
                  { name: 'currency0', type: 'address' },
                  { name: 'currency1', type: 'address' },
                  { name: 'fee', type: 'uint24' },
                  { name: 'tickSpacing', type: 'int24' },
                  { name: 'hooks', type: 'address' },
                ],
              },
              { name: 'zeroForOne', type: 'bool' },
              { name: 'hookData', type: 'bytes' },
            ],
          },
        ],
      },
      {
        name: 'p',
        type: 'tuple',
        components: [
          { name: 'tokenIn', type: 'address' },
          { name: 'tokenOut', type: 'address' },
          { name: 'amountSpecified', type: 'int256' },
          { name: 'minOut', type: 'uint256' },
          { name: 'hookMarginBps', type: 'uint16' },
          { name: 'probeGas', type: 'uint64' },
          { name: 'maxProbes', type: 'uint8' },
          { name: 'recipient', type: 'address' },
          { name: 'deadline', type: 'uint256' },
          { name: 'usePermit2', type: 'bool' },
          { name: 'permit', type: 'bytes' },
        ],
      },
    ],
    outputs: [{ name: 'out', type: 'uint256' }],
  },
  {
    type: 'event',
    name: 'Sworn',
    inputs: [
      { name: 'routeId', type: 'bytes32', indexed: true },
      { name: 'hook', type: 'address', indexed: true },
      { name: 'probed', type: 'uint256', indexed: false },
      { name: 'executed', type: 'uint256', indexed: false },
      { name: 'candidatesTried', type: 'uint8', indexed: false },
      { name: 'chosen', type: 'uint8', indexed: false },
    ],
  },
] as const;

export const hookBookAbi = [
  {
    type: 'function',
    name: 'score',
    stateMutability: 'view',
    inputs: [{ name: 'hook', type: 'address' }],
    outputs: [{ type: 'uint8' }],
  },
  {
    type: 'function',
    name: 'flags',
    stateMutability: 'view',
    inputs: [{ name: 'hook', type: 'address' }],
    outputs: [{ type: 'uint32' }],
  },
  {
    type: 'function',
    name: 'hasScore',
    stateMutability: 'view',
    inputs: [{ name: 'hook', type: 'address' }],
    outputs: [{ type: 'bool' }],
  },
  {
    type: 'function',
    name: 'scoreWithAge',
    stateMutability: 'view',
    inputs: [{ name: 'hook', type: 'address' }],
    outputs: [
      { name: 'score', type: 'uint8' },
      { name: 'ageSeconds', type: 'uint64' },
      { name: 'scored', type: 'bool' },
    ],
  },
] as const;
