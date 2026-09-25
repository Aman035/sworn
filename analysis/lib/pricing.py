"""Value swap outputs in USD, from the chain rather than from a price feed.

A protected-value number is only as trustworthy as its prices, and a third-party feed at
"roughly the right time" is not good enough when the claim is denominated in dollars. So
the only prices used here are ones the chain can be asked for at the exact block:

* a stablecoin output is taken at its face value in units;
* an ETH or WETH output is converted at the ETH/USD rate implied by the deepest hookless
  WETH/USDC pool **at that block**, quoted with the same machinery as everything else;
* anything else is **not priced at all**.

That last rule is the point. Refusing to price two thirds of the sample and saying so is
worth more than a complete table built on a guess, so every result carries the share it
could actually price.
"""

from __future__ import annotations

from dataclasses import dataclass

NATIVE = "0x0000000000000000000000000000000000000000"

# Face-value assets, lower-cased, with their decimals.
STABLES: dict[str, dict[str, int]] = {
    "base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 6,  # USDC
        "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": 6,  # USDbC
        "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2": 6,  # USDT
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": 18,  # DAI
    },
    "bnb": {
        "0x55d398326f99059ff775485246999027b3197955": 18,  # USDT
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": 18,  # USDC
    },
}

WETH: dict[str, str] = {
    "base": "0x4200000000000000000000000000000000000006",
    "bnb": "0x2170ed0880ac9a755fd29b2688956bd959f933f8",
}


@dataclass(frozen=True)
class Priced:
    usd: float | None
    basis: str  # "stable", "eth", or "" when unpriced


def is_eth(chain: str, currency: str) -> bool:
    c = currency.lower()
    return c == NATIVE or c == WETH.get(chain, "")


def price(chain: str, currency: str, amount: int, eth_usd: float | None) -> Priced:
    """USD value of `amount` raw units of `currency`, or `None` when it cannot be known."""
    c = currency.lower()
    stable = STABLES.get(chain, {}).get(c)
    if stable is not None:
        return Priced(amount / 10**stable, "stable")
    if is_eth(chain, c) and eth_usd is not None:
        return Priced(amount / 1e18 * eth_usd, "eth")
    return Priced(None, "")
