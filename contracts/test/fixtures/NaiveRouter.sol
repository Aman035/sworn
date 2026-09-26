// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {IUnlockCallback} from "v4-core/src/interfaces/callback/IUnlockCallback.sol";
import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {TickMath} from "v4-core/src/libraries/TickMath.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {SwapParams} from "v4-core/src/types/PoolOperation.sol";

/// @notice How routing works today: pick the route an off-chain quote liked, execute it,
///         and check the result against a slippage bound.
///
/// @dev This is the control for every comparison in this repo, and it is deliberately
///      *not* a strawman: it does exactly what a competent router does. The point is
///      that `minOut` cannot distinguish "the market moved" from "the hook lied": both
///      arrive as less output than expected, and a bound loose enough to tolerate normal
///      volatility is loose enough to let an 18% skim through.
contract NaiveRouter is IUnlockCallback {
    IPoolManager public immutable poolManager;

    error NotPoolManager();
    error InsufficientOutput(uint256 got, uint256 minOut);

    constructor(
        IPoolManager _poolManager
    ) {
        poolManager = _poolManager;
    }

    struct SwapRequest {
        PoolKey key;
        bool zeroForOne;
        int256 amountSpecified;
        uint256 minOut;
        address payer;
        address recipient;
    }

    function swap(
        PoolKey calldata key,
        bool zeroForOne,
        int256 amountSpecified,
        uint256 minOut,
        address recipient
    ) external returns (uint256 amountOut) {
        bytes memory result = poolManager.unlock(
            abi.encode(
                SwapRequest({
                    key: key,
                    zeroForOne: zeroForOne,
                    amountSpecified: amountSpecified,
                    minOut: minOut,
                    payer: msg.sender,
                    recipient: recipient
                })
            )
        );
        amountOut = abi.decode(result, (uint256));
    }

    function unlockCallback(
        bytes calldata data
    ) external override returns (bytes memory) {
        if (msg.sender != address(poolManager)) revert NotPoolManager();
        SwapRequest memory r = abi.decode(data, (SwapRequest));

        BalanceDelta delta = poolManager.swap(
            r.key,
            SwapParams({
                zeroForOne: r.zeroForOne,
                amountSpecified: r.amountSpecified,
                sqrtPriceLimitX96: r.zeroForOne ? TickMath.MIN_SQRT_PRICE + 1 : TickMath.MAX_SQRT_PRICE - 1
            }),
            ""
        );

        (int128 dIn, int128 dOut) =
            r.zeroForOne ? (delta.amount0(), delta.amount1()) : (delta.amount1(), delta.amount0());

        // v4 deltas are int128 by construction, so the magnitudes fit uint128.
        // forge-lint: disable-next-line(unsafe-typecast)
        uint256 amountIn = uint256(uint128(-dIn));
        // forge-lint: disable-next-line(unsafe-typecast)
        uint256 amountOut = uint256(uint128(dOut));

        // The only protection a naive router has.
        if (amountOut < r.minOut) revert InsufficientOutput(amountOut, r.minOut);

        Currency tokenIn = r.zeroForOne ? r.key.currency0 : r.key.currency1;
        Currency tokenOut = r.zeroForOne ? r.key.currency1 : r.key.currency0;

        poolManager.sync(tokenIn);
        // Test fixture: the mock token reverts on failure, and `settle()` would catch a
        // silent one by crediting zero. Production settlement is checked in SwornRouter.
        // forge-lint: disable-next-line(erc20-unchecked-transfer)
        IERC20Minimal(Currency.unwrap(tokenIn)).transferFrom(r.payer, address(poolManager), amountIn);
        poolManager.settle();
        poolManager.take(tokenOut, r.recipient, amountOut);

        return abi.encode(amountOut);
    }
}
