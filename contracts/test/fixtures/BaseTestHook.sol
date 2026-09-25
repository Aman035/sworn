// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {BeforeSwapDelta, BeforeSwapDeltaLibrary} from "v4-core/src/types/BeforeSwapDelta.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

/// @notice Minimal `IHooks` implementation for test fixtures.
/// @dev Every callback reverts unless a fixture overrides it, so a fixture cannot
///      accidentally depend on a permission its address does not actually grant.
abstract contract BaseTestHook is IHooks {
    error NotImplemented();
    error NotPoolManager();

    IPoolManager public immutable poolManager;

    constructor(
        IPoolManager _poolManager
    ) {
        poolManager = _poolManager;
    }

    modifier onlyPoolManager() {
        if (msg.sender != address(poolManager)) revert NotPoolManager();
        _;
    }

    function beforeInitialize(
        address,
        PoolKey calldata,
        uint160
    ) external virtual returns (bytes4) {
        revert NotImplemented();
    }

    function afterInitialize(
        address,
        PoolKey calldata,
        uint160,
        int24
    ) external virtual returns (bytes4) {
        revert NotImplemented();
    }

    function beforeAddLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        bytes calldata
    ) external virtual returns (bytes4) {
        revert NotImplemented();
    }

    function afterAddLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        BalanceDelta,
        BalanceDelta,
        bytes calldata
    ) external virtual returns (bytes4, BalanceDelta) {
        revert NotImplemented();
    }

    function beforeRemoveLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        bytes calldata
    ) external virtual returns (bytes4) {
        revert NotImplemented();
    }

    function afterRemoveLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        BalanceDelta,
        BalanceDelta,
        bytes calldata
    ) external virtual returns (bytes4, BalanceDelta) {
        revert NotImplemented();
    }

    function beforeSwap(
        address,
        PoolKey calldata,
        IPoolManager.SwapParams calldata,
        bytes calldata
    ) external virtual returns (bytes4, BeforeSwapDelta, uint24) {
        revert NotImplemented();
    }

    function afterSwap(
        address,
        PoolKey calldata,
        IPoolManager.SwapParams calldata,
        BalanceDelta,
        bytes calldata
    ) external virtual returns (bytes4, int128) {
        revert NotImplemented();
    }

    function beforeDonate(
        address,
        PoolKey calldata,
        uint256,
        uint256,
        bytes calldata
    ) external virtual returns (bytes4) {
        revert NotImplemented();
    }

    function afterDonate(
        address,
        PoolKey calldata,
        uint256,
        uint256,
        bytes calldata
    ) external virtual returns (bytes4) {
        revert NotImplemented();
    }
}

/// @notice A hook that skims a share of the swap input via `beforeSwapReturnDelta`.
///
/// @dev This is the mechanism behind every toxic fixture in this repo, isolated so each
///      variant only has to answer one question: *given this transaction, what fee?*
///      Subclasses override `_feeBps` and nothing else, which makes the difference
///      between an honest and a toxic hook exactly the thing being tested.
///
///      Taking is done on the *specified* currency: for an exact-input swap that is the
///      token the user is paying, so a positive `deltaSpecified` reduces the amount that
///      reaches the pool and the user receives correspondingly less output.
abstract contract SkimmingHook is BaseTestHook {
    uint256 internal constant BPS = 10_000;

    constructor(
        IPoolManager _poolManager
    ) BaseTestHook(_poolManager) {}

    /// @dev The whole attack surface, in one function.
    function _feeBps(
        address sender,
        PoolKey calldata key,
        IPoolManager.SwapParams calldata params
    ) internal virtual returns (uint256);

    function beforeSwap(
        address sender,
        PoolKey calldata key,
        IPoolManager.SwapParams calldata params,
        bytes calldata
    ) external virtual override onlyPoolManager returns (bytes4, BeforeSwapDelta, uint24) {
        uint256 bps = _feeBps(sender, key, params);
        if (bps == 0) {
            return (IHooks.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, 0);
        }

        // Only exact-input is skimmed; exact-output fixtures are covered separately.
        if (params.amountSpecified >= 0) {
            return (IHooks.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, 0);
        }

        uint256 amountIn = uint256(-params.amountSpecified);
        uint256 fee = (amountIn * bps) / BPS;
        if (fee == 0) {
            return (IHooks.beforeSwap.selector, BeforeSwapDeltaLibrary.ZERO_DELTA, 0);
        }

        Currency specified = params.zeroForOne ? key.currency0 : key.currency1;
        poolManager.take(specified, address(this), fee);

        // `fee` is a fraction of |amountSpecified|, which is itself an int256 that v4
        // constrains to int128 range, so this cannot truncate. Asserted rather than
        // assumed, because a truncating skim would silently under-charge and make the
        // fixture a weaker adversary than it claims to be.
        require(fee <= uint256(uint128(type(int128).max)), "skim overflows int128");

        // forge-lint: disable-next-line(unsafe-typecast)
        int128 skim = int128(uint128(fee));
        return (IHooks.beforeSwap.selector, toBeforeSwapDelta(skim, 0), 0);
    }
}

/// @dev Local copy of the helper so fixtures do not depend on a free function's import path.
function toBeforeSwapDelta(
    int128 deltaSpecified,
    int128 deltaUnspecified
) pure returns (BeforeSwapDelta beforeSwapDelta) {
    assembly ("memory-safe") {
        beforeSwapDelta := or(shl(128, deltaSpecified), and(sub(shl(128, 1), 1), deltaUnspecified))
    }
}
