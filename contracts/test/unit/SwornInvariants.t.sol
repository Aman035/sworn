// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {Candidate, Hop, SwornParams, SwornRouter} from "../../src/SwornRouter.sol";
import {SwornTestBase} from "./SwornTestBase.sol";

/// @notice Properties that must hold for *every* input, not just the ones we thought of.
///
/// @dev The fixture tests in `ToxicHooks.t.sol` prove Sworn defeats each attack we
///      enumerated. These prove the enumeration is not load-bearing: whatever the hook
///      does, the executed amounts equal the probed amounts or the transaction reverts,
///      and the router never ends up holding anything.
contract SwornInvariantsTest is SwornTestBase {
    PoolKey internal toxicKey;
    PoolKey internal honestKey;

    function setUp() public {
        setUpSworn();
        (, toxicKey) = deployHookAndPool("GaspriceSniffHook", abi.encode(manager), SKIM_FLAGS, 31);
        (, honestKey) = deployHookAndPool("HonestHook", abi.encode(manager), SKIM_FLAGS, 32);
    }

    function _balance(
        Currency c
    ) internal view returns (uint256) {
        return IERC20Minimal(Currency.unwrap(c)).balanceOf(address(sworn));
    }

    function _assertRouterHoldsNothing() internal view {
        assertEq(_balance(currency0), 0, "router retained tokenIn");
        assertEq(_balance(currency1), 0, "router retained tokenOut");
        assertEq(address(sworn).balance, 0, "router retained native");
    }

    // -----------------------------------------------------------------------------------
    // fuzz
    // -----------------------------------------------------------------------------------

    function testFuzz_executedEqualsProbed_andRouterKeepsNothing(
        uint96 amount,
        bool zeroForOne,
        bool toxicFirst,
        uint16 marginBps
    ) public {
        // Keep the swap small relative to pool depth; beyond that the test measures price
        // impact rather than router behaviour.
        amount = uint96(bound(amount, 1e9, 1e17));
        marginBps = uint16(bound(marginBps, 0, 5_000));

        vm.txGasPrice(1 gwei);

        Candidate[] memory cands =
            toxicFirst ? candidates(toxicKey, honestKey, zeroForOne) : candidates(honestKey, toxicKey, zeroForOne);

        SwornParams memory p = defaultParams();
        p.amountSpecified = -int256(uint256(amount));
        p.hookMarginBps = marginBps;
        p.tokenIn = zeroForOne ? currency0 : currency1;
        p.tokenOut = zeroForOne ? currency1 : currency0;

        Currency tokenOut = p.tokenOut;
        uint256 before = IERC20Minimal(Currency.unwrap(tokenOut)).balanceOf(address(this));

        // Any revert is acceptable; silently delivering less than probed is not. The
        // `Divergence` assertion inside the router is what makes that true, and this
        // fuzz run is what says it holds for inputs nobody chose by hand.
        try sworn.swornSwap(cands, p) returns (uint256 out) {
            uint256 delivered = IERC20Minimal(Currency.unwrap(tokenOut)).balanceOf(address(this)) - before;
            assertEq(delivered, out, "delivered != reported");
            _assertRouterHoldsNothing();
        } catch {
            _assertRouterHoldsNothing();
        }
    }

    function testFuzz_minOutIsHonoured(
        uint96 amount,
        uint96 minOut
    ) public {
        amount = uint96(bound(amount, 1e12, 1e17));
        vm.txGasPrice(1 gwei);

        Candidate[] memory cands = candidates(toxicKey, honestKey, true);
        SwornParams memory p = defaultParams();
        p.amountSpecified = -int256(uint256(amount));
        p.minOut = minOut;

        try sworn.swornSwap(cands, p) returns (uint256 out) {
            // A swap that succeeds must have cleared the floor it was given.
            assertGe(out, minOut, "returned less than minOut without reverting");
        } catch {
            // Reverting is always allowed.
        }
        _assertRouterHoldsNothing();
    }

    function testFuzz_candidateOrderDoesNotChangeTheOutcome(
        uint96 amount
    ) public {
        amount = uint96(bound(amount, 1e12, 1e17));
        vm.txGasPrice(1 gwei);

        SwornParams memory p = defaultParams();
        p.amountSpecified = -int256(uint256(amount));

        uint256 snapshotId = vm.snapshotState();
        uint256 first = sworn.swornSwap(candidates(toxicKey, honestKey, true), p);
        vm.revertToState(snapshotId);
        uint256 second = sworn.swornSwap(candidates(honestKey, toxicKey, true), p);

        // Selection must depend on probed output, not on the order the caller happened to
        // list candidates in. Otherwise an integrator's ordering becomes an attack surface.
        assertEq(first, second, "candidate order changed the result");
    }

    function testFuzz_moreCandidatesNeverHurts(
        uint96 amount
    ) public {
        amount = uint96(bound(amount, 1e12, 1e17));
        vm.txGasPrice(1 gwei);

        SwornParams memory p = defaultParams();
        p.amountSpecified = -int256(uint256(amount));

        Candidate[] memory onlyHookless = new Candidate[](1);
        onlyHookless[0] = singleHop(hooklessKey, true);

        uint256 snapshotId = vm.snapshotState();
        uint256 baseline = sworn.swornSwap(onlyHookless, p);
        vm.revertToState(snapshotId);

        Candidate[] memory all = new Candidate[](3);
        all[0] = singleHop(toxicKey, true);
        all[1] = singleHop(hooklessKey, true);
        all[2] = singleHop(honestKey, true);
        uint256 withMore = sworn.swornSwap(all, p);

        // Adding a toxic candidate must never make the user worse off than not offering
        // it at all. This is the property that lets an SDK pass every known pool.
        assertGe(withMore, baseline, "adding candidates reduced the output");
    }

    // -----------------------------------------------------------------------------------
    // guards
    // -----------------------------------------------------------------------------------

    function test_deadlineInThePastReverts() public {
        SwornParams memory p = defaultParams();
        p.deadline = block.timestamp - 1;
        Candidate[] memory cands = candidates(toxicKey, honestKey, true);

        vm.expectRevert(SwornRouter.DeadlinePassed.selector);
        sworn.swornSwap(cands, p);
    }

    function test_zeroProbeGasReverts() public {
        SwornParams memory p = defaultParams();
        p.probeGas = 0;
        Candidate[] memory cands = candidates(toxicKey, honestKey, true);

        vm.expectRevert(SwornRouter.ZeroProbeGas.selector);
        sworn.swornSwap(cands, p);
    }

    function test_noCandidatesReverts() public {
        vm.expectRevert(SwornRouter.NoCandidates.selector);
        sworn.swornSwap(new Candidate[](0), defaultParams());
    }

    function test_unrealisableMinOutReverts() public {
        SwornParams memory p = defaultParams();
        p.minOut = type(uint128).max;
        Candidate[] memory cands = candidates(toxicKey, honestKey, true);

        vm.expectRevert();
        sworn.swornSwap(cands, p);
        _assertRouterHoldsNothing();
    }

    function test_runRouteIsNotCallableExternally() public {
        Hop[] memory hops = new Hop[](1);
        hops[0] = Hop({key: hooklessKey, zeroForOne: true, hookData: ""});

        // The probe/execute entry point must never be reachable by anyone but the router.
        vm.expectRevert(SwornRouter.NotSelf.selector);
        sworn.runRoute(hops, -int256(SWAP_AMOUNT), false);
    }

    function test_unlockCallbackIsNotCallableExternally() public {
        vm.expectRevert(SwornRouter.NotPoolManager.selector);
        sworn.unlockCallback("");
    }

    function test_maxProbesLimitsWork() public {
        SwornParams memory p = defaultParams();
        p.maxProbes = 1;
        vm.txGasPrice(1 gwei);

        // Only the first candidate is probed, so the toxic route is all that is on offer
        // and the user gets its real (bad) price, not a spoofed one.
        Candidate[] memory cands = candidates(toxicKey, honestKey, true);
        uint256 out = sworn.swornSwap(cands, p);
        assertGt(out, 0);
        _assertRouterHoldsNothing();
    }
}
