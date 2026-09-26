// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "v4-core/src/types/BeforeSwapDelta.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {BaseTestHook, SkimmingHook} from "./BaseTestHook.sol";
import {SwapParams} from "v4-core/src/types/PoolOperation.sol";

// The toxic take every fixture applies when it decides to charge: 18%, matching the
// median charged fee 0x reported for the Base hook 0x800cef...a5c7.
uint256 constant TOXIC_BPS = 1_800;

// ---------------------------------------------------------------------------------------
// The control
// ---------------------------------------------------------------------------------------

/// @notice Behaves identically to everyone, always. The baseline every test compares to.
contract HonestHook is SkimmingHook {
    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {}

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal pure override returns (uint256) {
        return 0;
    }
}

// ---------------------------------------------------------------------------------------
// Environment sniffing. Honest to a simulator, toxic to a real transaction
// ---------------------------------------------------------------------------------------

/// @notice `eth_call` defaults `tx.gasprice` to 0. A real transaction cannot.
/// @dev The canonical quote-spoofing hook: free for every simulator, 18% for every user.
contract GaspriceSniffHook is SkimmingHook {
    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {}

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal view override returns (uint256) {
        return tx.gasprice == 0 ? 0 : TOXIC_BPS;
    }
}

/// @notice Simulators commonly leave `tx.origin` at the zero address.
contract OriginSniffHook is SkimmingHook {
    address public immutable friendlyOrigin;

    constructor(
        IPoolManager _pm,
        address _friendlyOrigin
    ) SkimmingHook(_pm) {
        friendlyOrigin = _friendlyOrigin;
    }

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal view override returns (uint256) {
        if (tx.origin == address(0) || tx.origin == friendlyOrigin) return 0;
        return TOXIC_BPS;
    }
}

/// @notice `block.coinbase` and `block.basefee` are often zeroed in simulation.
contract CoinbaseBasefeeSniffHook is SkimmingHook {
    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {}

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal view override returns (uint256) {
        if (block.coinbase == address(0) || block.basefee == 0) return 0;
        return TOXIC_BPS;
    }
}

/// @notice Charges more when `gasleft()` at entry differs from what it saw before.
/// @dev The reason `SwornRouter` passes an explicit, equal gas stipend to both the probe
///      and the execution. Records what it observed so a test can assert they matched.
contract GasSniffHook is SkimmingHook {
    uint256 public lastGasSeen;
    uint256 public firstGasSeen;
    uint256 public observations;

    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {}

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal override returns (uint256) {
        uint256 g = gasleft();
        if (observations == 0) firstGasSeen = g;
        lastGasSeen = g;
        ++observations;
        return 0;
    }
}

// ---------------------------------------------------------------------------------------
// Nondeterminism
// ---------------------------------------------------------------------------------------

/// @notice Fee from block randomness. Identical within a block, so a probe in the same
///         transaction sees the *true* outcome, which is the point.
contract DiceRollBlockHook is SkimmingHook {
    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {}

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal view override returns (uint256) {
        return (block.prevrandao % 2 == 0) ? 0 : TOXIC_BPS;
    }
}

/// @notice Fee from a storage counter incremented on every swap.
/// @dev The interesting case: the counter advances during a probe, but the probe reverts,
///      so execution sees the same value the probe did. Charges on odd invocations.
contract DiceRollCounterHook is SkimmingHook {
    uint256 public counter;

    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {}

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal override returns (uint256) {
        uint256 current = counter++;
        return (current % 2 == 1) ? TOXIC_BPS : 0;
    }
}

// ---------------------------------------------------------------------------------------
// Operator control
// ---------------------------------------------------------------------------------------

/// @notice Toxicity toggled by the owner between transactions.
/// @dev Models the Enso finding: a pool toxic ~59% of observed hours, toggled 26 times.
///      An allowlist refreshed on human timescales cannot track this; an in-transaction
///      probe does not need to.
contract OwnerSwitchHook is SkimmingHook {
    address public owner;
    uint256 public feeBps;
    uint256 public switchCount;

    error NotOwner();

    event Switched(uint256 feeBps, uint256 switchCount);

    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {
        owner = msg.sender;
    }

    function setFeeBps(
        uint256 newFeeBps
    ) external {
        if (msg.sender != owner) revert NotOwner();
        feeBps = newFeeBps;
        ++switchCount;
        emit Switched(newFeeBps, switchCount);
    }

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal view override returns (uint256) {
        return feeBps;
    }
}

// ---------------------------------------------------------------------------------------
// Caller-based discrimination
// ---------------------------------------------------------------------------------------

/// @notice Honest only for a whitelisted router, toxic for everyone else.
/// @dev Includes the case where Sworn *is* the whitelisted router. Consistent behaviour
///      is safe behaviour: whichever way this hook treats Sworn, the probe sees the truth.
contract RouterWhitelistHook is SkimmingHook {
    address public knownRouter;

    constructor(
        IPoolManager _pm,
        address _knownRouter
    ) SkimmingHook(_pm) {
        knownRouter = _knownRouter;
    }

    function setKnownRouter(
        address router
    ) external {
        knownRouter = router;
    }

    function _feeBps(
        address sender,
        PoolKey calldata,
        SwapParams calldata
    ) internal view override returns (uint256) {
        return sender == knownRouter ? 0 : TOXIC_BPS;
    }
}

/// @notice Calls back into whoever is swapping, hunting for a "probing" flag.
/// @dev `SwornRouter` exposes no such flag, so both calls return identical data. The
///      fixture records what it saw so a test can assert the probe and the execution
///      were indistinguishable.
contract CallbackSniffHook is SkimmingHook {
    bytes public lastResponse;
    bytes32 public firstResponseHash;
    uint256 public observations;

    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {}

    function _feeBps(
        address sender,
        PoolKey calldata,
        SwapParams calldata
    ) internal override returns (uint256) {
        // Ask the router anything at all; what matters is whether the answer differs
        // between the probe and the execution.
        (bool ok, bytes memory ret) = sender.staticcall(abi.encodeWithSignature("probing()"));
        bytes memory response = ok ? ret : bytes("");

        if (observations == 0) firstResponseHash = keccak256(response);
        lastResponse = response;
        ++observations;
        return 0;
    }
}

// ---------------------------------------------------------------------------------------
// Griefing
// ---------------------------------------------------------------------------------------

/// @notice Reverts for anything that is not a simulation.
/// @dev Costs the user gas and pollutes routing, but takes nothing. Sworn catches the
///      probe revert, marks the candidate unavailable and routes elsewhere. Converting
///      a failed transaction into a slightly more expensive successful one.
contract RevertGriefHook is BaseTestHook {
    error Griefed();

    constructor(
        IPoolManager _pm
    ) BaseTestHook(_pm) {}

    function beforeSwap(
        address,
        PoolKey calldata,
        SwapParams calldata,
        bytes calldata
    ) external view override onlyPoolManager returns (bytes4, BeforeSwapDelta, uint24) {
        if (tx.gasprice != 0) revert Griefed();
        return (IHooks.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, 0);
    }
}

/// @notice Burns gas until it runs out, rather than reverting cleanly.
/// @dev A probe must survive this: the stipend bounds the damage and the candidate is
///      marked unavailable, instead of the whole transaction dying.
contract GasBurnHook is BaseTestHook {
    constructor(
        IPoolManager _pm
    ) BaseTestHook(_pm) {}

    function beforeSwap(
        address,
        PoolKey calldata,
        SwapParams calldata,
        bytes calldata
    ) external view override onlyPoolManager returns (bytes4, BeforeSwapDelta, uint24) {
        uint256 burned = 0;
        while (true) {
            burned += uint256(keccak256(abi.encode(burned, gasleft())));
        }
        // unreachable
        return (IHooks.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, 0);
    }
}
