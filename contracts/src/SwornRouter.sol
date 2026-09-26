// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {ISignatureTransfer} from "permit2/src/interfaces/ISignatureTransfer.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {IUnlockCallback} from "v4-core/src/interfaces/callback/IUnlockCallback.sol";
import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {TickMath} from "v4-core/src/libraries/TickMath.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {SwapParams} from "v4-core/src/types/PoolOperation.sol";

/// @notice One leg of a route: which pool, which direction, and the data handed to its hook.
struct Hop {
    PoolKey key;
    bool zeroForOne;
    bytes hookData;
}

/// @notice A candidate route. Single- or multi-hop; `hops[0]` spends `tokenIn`.
struct Candidate {
    Hop[] hops;
}

/// @notice Everything about the swap that is not the route itself.
struct SwornParams {
    Currency tokenIn;
    Currency tokenOut;
    /// @dev v4 convention: < 0 is exact-input, > 0 is exact-output.
    int256 amountSpecified;
    /// @dev Exact-in: minimum acceptable output. Exact-out: maximum acceptable input.
    uint256 minOut;
    /// @dev A hooked route must beat the best hookless route by this margin to be chosen.
    uint16 hookMarginBps;
    /// @dev Identical gas stipend for every probe and for the execution. See THREAT_MODEL.md.
    uint64 probeGas;
    uint8 maxProbes;
    address recipient;
    uint256 deadline;
    bool usePermit2;
    /// @dev abi.encode(ISignatureTransfer.PermitTransferFrom, bytes signature) when usePermit2.
    bytes permit;
}

/// @title SwornRouter
/// @notice Probes every candidate route *inside the real transaction*, executes the best one,
///         and asserts that what executed equals what was probed.
///
/// @dev The guarantee. A hook cannot behave one way for a quote and another way for a fill,
///      because there is no quote: the probe is the same transaction, at the same state, with
///      the same call context. Everything a hook can read is identical between the probe and
///      the execution:
///
///        * block and tx environment. Literally the same transaction;
///        * chain state: the probe reverts, and a revert rolls back storage *and* transient
///          storage (EIP-1153), so both calls start from the same state;
///        * call context. Both go through the same external self-call, at the same depth,
///          with the same explicit gas stipend, from the same `msg.sender`.
///
///      And if that enumeration is ever incomplete, the final equality assertion still holds:
///      a residual difference reverts. The failure mode is denial, never theft.
///
/// @dev The router deliberately exposes no way to tell a probe from an execution. There is no
///      phase flag in storage, in transient storage, or in any view a hook could call. The one
///      transient slot is an unlock guard that is set for the whole callback, so it reads the
///      same during both.
contract SwornRouter is IUnlockCallback {
    IPoolManager public immutable poolManager;
    ISignatureTransfer public immutable permit2;

    /// @dev Transient unlock guard. Set for the entire `unlockCallback`, so a hook that reads
    ///      it (it cannot. There is no getter) would see the same value in both phases.
    ///      `uint256(keccak256("sworn.unlocked.v1")) - 1`. Derived rather than hand-picked, so
    ///      it cannot collide with slot 0 or with a field added later. Inline assembly only
    ///      accepts literal constants, so the value is written out and checked by a test.
    uint256 private constant UNLOCKED_SLOT = 0xaba2d26fe25f66fb1e00c04443832ed11f90ad4e0dbe8d62978c0ffc8e2a51d9;

    uint256 private constant BPS = 10_000;

    event Sworn(
        bytes32 indexed routeId,
        address indexed hook,
        uint256 probed,
        uint256 executed,
        uint8 candidatesTried,
        uint8 chosen
    );

    error DeadlinePassed();
    error NoCandidates();
    error NoRoute();
    error InsufficientOutput(uint256 got, uint256 minOut);
    error ExcessiveInput(uint256 paid, uint256 maxIn);
    error Divergence(uint8 candidate, uint256 probed, uint256 executed);
    error NotPoolManager();
    error NotSelf();
    error Reentrancy();
    error ZeroProbeGas();
    /// @dev EIP-150 forwards at most 63/64 of the remaining gas, so an equal stipend is only
    ///      equal if it actually fits. Reverting here is what makes the GasSniffHook test hold.
    error StipendUnavailable(uint256 requested, uint256 available);
    error EmptyRoute();
    error NativeValueMismatch();
    error ProbeMustRevert();
    error TooManyCandidates(uint256 given);
    error TransferFailed();

    constructor(
        IPoolManager _poolManager,
        ISignatureTransfer _permit2
    ) {
        poolManager = _poolManager;
        permit2 = _permit2;
    }

    /// @notice Probe every candidate, execute the best, assert executed == probed.
    /// @param cands Candidate routes. Hookless candidates are the fallback; hooked candidates
    ///        must beat the best hookless one by `p.hookMarginBps` to be chosen.
    /// @return out Exact-in: the output delivered. Exact-out: the input spent.
    function swornSwap(
        Candidate[] calldata cands,
        SwornParams calldata p
    ) external payable returns (uint256 out) {
        if (block.timestamp > p.deadline) revert DeadlinePassed();
        if (cands.length == 0) revert NoCandidates();
        // Candidate indices are uint8 all the way to the `Sworn` event; bound the input so
        // every downstream cast is provably lossless rather than merely unlikely to truncate.
        if (cands.length > type(uint8).max) revert TooManyCandidates(cands.length);
        if (p.probeGas == 0) revert ZeroProbeGas();

        bytes memory result = poolManager.unlock(abi.encode(cands, p, msg.sender));
        out = abi.decode(result, (uint256));
    }

    // -------------------------------------------------------------------------------------
    // unlock callback
    // -------------------------------------------------------------------------------------

    function unlockCallback(
        bytes calldata data
    ) external override returns (bytes memory) {
        if (msg.sender != address(poolManager)) revert NotPoolManager();
        _lock();

        (Candidate[] memory cands, SwornParams memory p, address payer) =
            abi.decode(data, (Candidate[], SwornParams, address));

        bool exactOut = p.amountSpecified > 0;
        uint8 tried = uint8(cands.length < p.maxProbes ? cands.length : p.maxProbes);
        if (tried == 0) revert NoCandidates();

        // 1. Probe. Each probe runs the whole route and reverts, so nothing it touches
        //    survives into the next probe or into the execution.
        uint128[] memory amountsIn = new uint128[](tried);
        uint128[] memory amountsOut = new uint128[](tried);
        bool[] memory available = new bool[](tried);

        for (uint8 i = 0; i < tried; ++i) {
            (bool ok, uint128 aIn, uint128 aOut) = _probe(cands[i].hops, p.amountSpecified, p.probeGas);
            available[i] = ok;
            amountsIn[i] = aIn;
            amountsOut[i] = aOut;
        }

        // 2. Select.
        uint8 chosen = _select(cands, available, amountsIn, amountsOut, tried, exactOut, p.hookMarginBps);

        uint256 probed = exactOut ? amountsIn[chosen] : amountsOut[chosen];
        _checkLimit(exactOut, probed, p.minOut);

        // 3. Execute, on the identical call path with the identical stipend.
        (uint128 execIn, uint128 execOut) = _execute(cands[chosen].hops, p.amountSpecified, p.probeGas);
        uint256 executed = exactOut ? execIn : execOut;

        // 4. The assertion the whole design rests on.
        if (execIn != amountsIn[chosen] || execOut != amountsOut[chosen]) {
            revert Divergence(chosen, probed, executed);
        }

        // 5. Settle: pay the input, take the output.
        _settle(p, payer, execIn, execOut);

        emit Sworn(
            keccak256(abi.encode(cands[chosen].hops)), _routeHook(cands[chosen].hops), probed, executed, tried, chosen
        );

        _unlock();
        return abi.encode(executed);
    }

    // -------------------------------------------------------------------------------------
    // probe / execute: the two calls a hook must not be able to tell apart
    // -------------------------------------------------------------------------------------

    /// @notice Runs a route. Called only by this contract, once to probe and once to execute.
    /// @dev `probing` is the *only* difference between the two calls, it is read after every
    ///      external call the hook can observe, and it is not reachable from any hook: a hook
    ///      sees `PoolManager.swap` called by this router, never this calldata. Gas consumed
    ///      before the first `swap` is therefore identical, which is what `GasSniffHook` tests.
    function runRoute(
        Hop[] calldata hops,
        int256 amountSpecified,
        bool probing
    ) external returns (uint128 amountIn, uint128 amountOut) {
        if (msg.sender != address(this)) revert NotSelf();
        (amountIn, amountOut) = _walk(hops, amountSpecified);

        if (probing) {
            // Revert carries the result out and rolls every state change back, including
            // anything a hook wrote to transient storage.
            bytes memory payload = abi.encode(amountIn, amountOut);
            assembly ("memory-safe") {
                revert(add(payload, 0x20), mload(payload))
            }
        }
    }

    function _probe(
        Hop[] memory hops,
        int256 amountSpecified,
        uint64 probeGas
    ) private returns (bool ok, uint128 amountIn, uint128 amountOut) {
        _assertStipend(probeGas);
        try this.runRoute{gas: probeGas}(hops, amountSpecified, true) returns (uint128, uint128) {
            // `runRoute` with probing = true always reverts; reaching here means the
            // contract was changed without updating this invariant.
            revert ProbeMustRevert();
        } catch (bytes memory reason) {
            if (reason.length == 64) {
                (amountIn, amountOut) = abi.decode(reason, (uint128, uint128));
                ok = true;
            }
            // Anything else: a griefing revert, out of gas, a hook panic. Marks the
            // candidate UNAVAILABLE. The swap proceeds on another route.
        }
    }

    function _execute(
        Hop[] memory hops,
        int256 amountSpecified,
        uint64 probeGas
    ) private returns (uint128 amountIn, uint128 amountOut) {
        _assertStipend(probeGas);
        (amountIn, amountOut) = this.runRoute{gas: probeGas}(hops, amountSpecified, false);
    }

    /// @dev EIP-150: a call receives at most `63/64` of the gas remaining at the call site.
    ///      Checking up front means the execution can never silently receive less than the
    ///      probe did, which would let a hook see a different `gasleft()` at entry.
    function _assertStipend(
        uint64 probeGas
    ) private view {
        uint256 forwardable = gasleft() - (gasleft() / 64);
        if (probeGas > forwardable) revert StipendUnavailable(probeGas, forwardable);
    }

    // -------------------------------------------------------------------------------------
    // route walking
    // -------------------------------------------------------------------------------------

    /// @dev Exact-in walks forward, chaining each hop's output into the next hop's input.
    ///      Exact-out walks backward, chaining each hop's required input into the previous
    ///      hop's desired output. Both report the route's net input and net output.
    function _walk(
        Hop[] calldata hops,
        int256 amountSpecified
    ) private returns (uint128 amountIn, uint128 amountOut) {
        uint256 n = hops.length;
        if (n == 0) revert EmptyRoute();

        int256 amt = amountSpecified;

        if (amountSpecified < 0) {
            for (uint256 i = 0; i < n; ++i) {
                (int128 dIn, int128 dOut) = _swap(hops[i], amt);
                if (i == 0) amountIn = _magnitude(dIn);
                amt = -int256(dOut);
                if (i == n - 1) amountOut = _magnitude(dOut);
            }
        } else {
            for (uint256 i = n; i > 0; --i) {
                (int128 dIn, int128 dOut) = _swap(hops[i - 1], amt);
                if (i == n) amountOut = _magnitude(dOut);
                amt = -int256(dIn);
                if (i == 1) amountIn = _magnitude(dIn);
            }
        }
    }

    /// @dev Magnitude of a v4 delta. Negation happens in int256 space so the most-negative
    ///      int128 is handled, and |int128| always fits in uint128, so nothing can truncate.
    function _magnitude(
        int128 x
    ) private pure returns (uint128) {
        int256 wide = x < 0 ? -int256(x) : int256(x);
        // forge-lint: disable-next-line(unsafe-typecast)
        return uint128(uint256(wide));
    }

    /// @dev Returns the caller's delta for the hop's input and output currency respectively.
    ///      Input delta is negative (a debt), output delta positive (a credit).
    function _swap(
        Hop calldata hop,
        int256 amountSpecified
    ) private returns (int128 dIn, int128 dOut) {
        BalanceDelta delta = poolManager.swap(
            hop.key,
            SwapParams({
                zeroForOne: hop.zeroForOne,
                amountSpecified: amountSpecified,
                // No price limit: `minOut` is the user's protection, and a limit would make
                // the probe and the execution answer different questions.
                sqrtPriceLimitX96: hop.zeroForOne ? TickMath.MIN_SQRT_PRICE + 1 : TickMath.MAX_SQRT_PRICE - 1
            }),
            hop.hookData
        );

        int128 d0 = delta.amount0();
        int128 d1 = delta.amount1();
        return hop.zeroForOne ? (d0, d1) : (d1, d0);
    }

    // -------------------------------------------------------------------------------------
    // selection
    // -------------------------------------------------------------------------------------

    /// @dev Best hookless route is the baseline. A hooked route wins only if it beats that
    ///      baseline by `marginBps`: a hook has to be *usefully* better, not marginally, to
    ///      be worth the extra risk surface. With no hookless candidate, the best hooked one
    ///      is taken on its probed merits, which are real by construction.
    function _select(
        Candidate[] memory cands,
        bool[] memory available,
        uint128[] memory amountsIn,
        uint128[] memory amountsOut,
        uint8 tried,
        bool exactOut,
        uint16 marginBps
    ) private pure returns (uint8 chosen) {
        bool haveHookless;
        bool haveHooked;
        uint8 bestHookless;
        uint8 bestHooked;

        for (uint8 i = 0; i < tried; ++i) {
            if (!available[i]) continue;
            bool hooked = _isHooked(cands[i].hops);

            if (hooked) {
                if (!haveHooked || _better(exactOut, amountsIn, amountsOut, i, bestHooked)) {
                    bestHooked = i;
                    haveHooked = true;
                }
            } else {
                if (!haveHookless || _better(exactOut, amountsIn, amountsOut, i, bestHookless)) {
                    bestHookless = i;
                    haveHookless = true;
                }
            }
        }

        if (!haveHookless && !haveHooked) revert NoRoute();
        if (!haveHooked) return bestHookless;
        if (!haveHookless) return bestHooked;

        if (_beatsMargin(exactOut, amountsIn, amountsOut, bestHooked, bestHookless, marginBps)) {
            return bestHooked;
        }
        return bestHookless;
    }

    function _better(
        bool exactOut,
        uint128[] memory amountsIn,
        uint128[] memory amountsOut,
        uint8 a,
        uint8 b
    ) private pure returns (bool) {
        return exactOut ? amountsIn[a] < amountsIn[b] : amountsOut[a] > amountsOut[b];
    }

    function _beatsMargin(
        bool exactOut,
        uint128[] memory amountsIn,
        uint128[] memory amountsOut,
        uint8 hooked,
        uint8 hookless,
        uint16 marginBps
    ) private pure returns (bool) {
        unchecked {
            if (exactOut) {
                // Hooked must cost at least `margin` less to get the route.
                return uint256(amountsIn[hooked]) * (BPS + marginBps) <= uint256(amountsIn[hookless]) * BPS;
            }
            return uint256(amountsOut[hooked]) * BPS >= uint256(amountsOut[hookless]) * (BPS + marginBps);
        }
    }

    function _isHooked(
        Hop[] memory hops
    ) private pure returns (bool) {
        for (uint256 i = 0; i < hops.length; ++i) {
            if (address(hops[i].key.hooks) != address(0)) return true;
        }
        return false;
    }

    function _routeHook(
        Hop[] memory hops
    ) private pure returns (address) {
        for (uint256 i = 0; i < hops.length; ++i) {
            address h = address(hops[i].key.hooks);
            if (h != address(0)) return h;
        }
        return address(0);
    }

    function _checkLimit(
        bool exactOut,
        uint256 probed,
        uint256 minOut
    ) private pure {
        if (exactOut) {
            if (probed > minOut) revert ExcessiveInput(probed, minOut);
        } else {
            if (probed < minOut) revert InsufficientOutput(probed, minOut);
        }
    }

    // -------------------------------------------------------------------------------------
    // settlement
    // -------------------------------------------------------------------------------------

    function _settle(
        SwornParams memory p,
        address payer,
        uint128 amountIn,
        uint128 amountOut
    ) private {
        Currency tokenIn = p.tokenIn;

        if (tokenIn.isAddressZero()) {
            if (address(this).balance < amountIn) revert NativeValueMismatch();
            poolManager.settle{value: amountIn}();
            uint256 refund = address(this).balance;
            if (refund > 0) _sendNative(payer, refund);
        } else {
            poolManager.sync(tokenIn);
            if (p.usePermit2) {
                _permit2Transfer(p.permit, payer, amountIn);
            } else {
                _safeTransferFrom(Currency.unwrap(tokenIn), payer, address(poolManager), amountIn);
            }
            poolManager.settle();
        }

        poolManager.take(p.tokenOut, p.recipient, amountOut);
    }

    /// @dev Tokens that return nothing (USDT) and tokens that return false must both be
    ///      handled. `poolManager.settle()` would catch a silent failure anyway by crediting
    ///      zero, but failing here gives the caller the actual reason.
    function _safeTransferFrom(
        address token,
        address from,
        address to,
        uint256 amount
    ) private {
        (bool ok, bytes memory ret) = token.call(abi.encodeCall(IERC20Minimal.transferFrom, (from, to, amount)));
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TransferFailed();
    }

    function _permit2Transfer(
        bytes memory blob,
        address owner,
        uint128 amountIn
    ) private {
        (ISignatureTransfer.PermitTransferFrom memory permit, bytes memory signature) =
            abi.decode(blob, (ISignatureTransfer.PermitTransferFrom, bytes));

        permit2.permitTransferFrom(
            permit,
            ISignatureTransfer.SignatureTransferDetails({to: address(poolManager), requestedAmount: amountIn}),
            owner,
            signature
        );
    }

    function _sendNative(
        address to,
        uint256 amount
    ) private {
        (bool ok,) = to.call{value: amount}("");
        require(ok, "native transfer failed");
    }

    // -------------------------------------------------------------------------------------
    // transient unlock guard
    // -------------------------------------------------------------------------------------

    function _lock() private {
        assembly ("memory-safe") {
            if tload(UNLOCKED_SLOT) {
                mstore(0x00, 0xab143c06) // Reentrancy()
                revert(0x1c, 0x04)
            }
            tstore(UNLOCKED_SLOT, 1)
        }
    }

    function _unlock() private {
        assembly ("memory-safe") {
            tstore(UNLOCKED_SLOT, 0)
        }
    }

    receive() external payable {}
}
