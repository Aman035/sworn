"""Minimal EVM bytecode scanning: opcodes, selectors, proxy patterns.

Static analysis of hook bytecode underpins the census (upgradeable? owner-gated?) and the
Phase 4 probe (does it even *contain* an env opcode?).

The one detail that matters more than any other here: **PUSH immediates must be skipped**.
A naive `0x3a in code` test reports `GASPRICE` in almost every contract, because 0x3a
appears constantly inside pushed constants, addresses and jump tables. Every scan below
walks the instruction stream properly, and there is a test that a byte hidden inside PUSH
data is not counted.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field

# Opcodes that expose the transaction/block environment. The ones Sworn cares about are
# those a hook could use to tell a simulation from a real fill.
ENV_OPCODES: dict[int, str] = {
    0x32: "ORIGIN",
    0x3A: "GASPRICE",
    0x41: "COINBASE",
    0x42: "TIMESTAMP",
    0x43: "NUMBER",
    0x44: "PREVRANDAO",
    0x45: "GASLIMIT",
    0x46: "CHAINID",
    0x48: "BASEFEE",
    0x5A: "GAS",
}

# Opcodes worth flagging for other reasons.
NOTABLE_OPCODES: dict[int, str] = {
    0xFF: "SELFDESTRUCT",
    0xF4: "DELEGATECALL",
    0xF0: "CREATE",
    0xF5: "CREATE2",
    0x5C: "TLOAD",
    0x5D: "TSTORE",
}

PUSH1 = 0x60
PUSH32 = 0x7F
PUSH0 = 0x5F

# EIP-1967 storage slots.
EIP1967_IMPLEMENTATION = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_BEACON = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
EIP1967_ADMIN = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
# EIP-1822 (UUPS proxiable).
EIP1822_PROXIABLE = "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"


@dataclass
class Instruction:
    offset: int
    opcode: int
    immediate: bytes = b""


def strip_metadata(code: bytes) -> bytes:
    """Drop the Solidity CBOR metadata trailer, if present.

    The last two bytes give the metadata length. Leaving it in produces phantom opcodes
    at the end of the stream and, worse, phantom 4-byte "selectors" from the IPFS hash.
    """
    if len(code) < 2:
        return code
    length = int.from_bytes(code[-2:], "big")
    if 0 < length <= len(code) - 2:
        return code[: -(length + 2)]
    return code


def iter_instructions(code: bytes) -> Iterator[Instruction]:
    """Walk the instruction stream, skipping PUSH immediates."""
    i = 0
    n = len(code)
    while i < n:
        op = code[i]
        if PUSH1 <= op <= PUSH32:
            size = op - PUSH1 + 1
            immediate = code[i + 1 : i + 1 + size]
            yield Instruction(i, op, immediate)
            i += 1 + size
        else:
            yield Instruction(i, op)
            i += 1


def opcodes_present(code: bytes, table: dict[int, str]) -> set[str]:
    """Which of `table`'s opcodes actually appear as instructions."""
    found: set[str] = set()
    for instruction in iter_instructions(code):
        name = table.get(instruction.opcode)
        if name:
            found.add(name)
    return found


def env_opcodes(code: bytes) -> set[str]:
    return opcodes_present(code, ENV_OPCODES)


def notable_opcodes(code: bytes) -> set[str]:
    return opcodes_present(code, NOTABLE_OPCODES)


def function_selectors(code: bytes) -> set[str]:
    """4-byte selectors pushed by the dispatcher.

    Heuristic but effective: solc compares `msg.sig` against `PUSH4` constants. False
    positives are possible (a PUSH4 of some other constant), which is why selectors are
    only ever used as *signals*, never as proof.
    """
    out: set[str] = set()
    for instruction in iter_instructions(code):
        if instruction.opcode == 0x63 and len(instruction.immediate) == 4:  # PUSH4
            out.add("0x" + instruction.immediate.hex())
    return out


def is_minimal_proxy(code: bytes) -> bool:
    """EIP-1167 minimal proxy: a 45-byte stub that delegatecalls a fixed address."""
    hexcode = code.hex()
    return (
        len(code) in (45, 55)
        and hexcode.startswith("363d3d373d3d3d363d")
        and hexcode.endswith("5af43d82803e903d91602b57fd5bf3")
    )


@dataclass
class BytecodeReport:
    address: str
    size: int
    sha256: str
    env_opcodes: list[str] = field(default_factory=list)
    notable: list[str] = field(default_factory=list)
    selectors: list[str] = field(default_factory=list)
    minimal_proxy: bool = False
    has_delegatecall: bool = False
    has_selfdestruct: bool = False


def analyse(address: str, code: bytes) -> BytecodeReport:
    body = strip_metadata(code)
    notable = notable_opcodes(body)
    return BytecodeReport(
        address=address.lower(),
        size=len(code),
        sha256=hashlib.sha256(code).hexdigest(),
        env_opcodes=sorted(env_opcodes(body)),
        notable=sorted(notable),
        selectors=sorted(function_selectors(body)),
        minimal_proxy=is_minimal_proxy(code),
        has_delegatecall="DELEGATECALL" in notable,
        has_selfdestruct="SELFDESTRUCT" in notable,
    )
