// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {Candidate, Hop, SwornParams, SwornRouter} from "../../src/SwornRouter.sol";
import {SwornTestBase} from "./SwornTestBase.sol";

/// @notice Route shapes: exact-output, and multi-hop in both directions.
///
/// @dev These are the paths where the sign conventions are easy to get wrong. Exact-out
///      walks the route backwards, chaining each hop's required input into the previous
///      hop's desired output, and compares on the *input* side, so `minOut` becomes a
///      maximum rather than a minimum.
contract SwornRoutesTest is SwornTestBase {
    PoolKey internal toxicKey;
    PoolKey internal honestKey;

    function setUp() public {
        setUpSworn();
        (, toxicKey) = deployHookAndPool("GaspriceSniffHook", abi.encode(manager), SKIM_FLAGS, 41);
        (, honestKey) = deployHookAndPool("HonestHook", abi.encode(manager), SKIM_FLAGS, 42);
    }

    function _bal(
        Currency c
    ) internal view returns (uint256) {
        return IERC20Minimal(Currency.unwrap(c)).balanceOf(address(this));
    }

    function _assertRouterEmpty() internal view {
        assertEq(_swornBal(currency0), 0, "router kept tokenIn");
        assertEq(_swornBal(currency1), 0, "router kept tokenOut");
    }

    function _swornBal(
        Currency c
    ) internal view returns (uint256) {
        return IERC20Minimal(Currency.unwrap(c)).balanceOf(address(sworn));
    }

    // -----------------------------------------------------------------------------------
    // exact output
    // -----------------------------------------------------------------------------------

    function _exactOutParams(
        uint256 wantOut,
        uint256 maxIn
    ) internal view returns (SwornParams memory p) {
        p = defaultParams();
        // v4 convention: a positive amountSpecified is exact-output.
        p.amountSpecified = int256(wantOut);
        // For exact-out, `minOut` carries the maximum acceptable input.
        p.minOut = maxIn;
    }

    function test_exactOut_deliversExactlyTheRequestedOutput() public {
        uint256 wantOut = 1e14;
        Candidate[] memory cands = new Candidate[](1);
        cands[0] = singleHop(hooklessKey, true);

        uint256 outBefore = _bal(currency1);
        uint256 inBefore = _bal(currency0);

        uint256 spent = sworn.swornSwap(cands, _exactOutParams(wantOut, type(uint128).max));

        assertEq(_bal(currency1) - outBefore, wantOut, "did not deliver the exact output");
        assertEq(inBefore - _bal(currency0), spent, "reported input differs from what was paid");
        _assertRouterEmpty();
    }

    function test_exactOut_routesAroundAToxicHook() public {
        vm.txGasPrice(1 gwei);
        uint256 wantOut = 1e14;

        Candidate[] memory both = candidates(toxicKey, hooklessKey, true);
        uint256 spentBoth = sworn.swornSwap(both, _exactOutParams(wantOut, type(uint128).max));

        uint256 snapshotId = vm.snapshotState();
        Candidate[] memory onlyHookless = new Candidate[](1);
        onlyHookless[0] = singleHop(hooklessKey, true);
        uint256 spentHookless = sworn.swornSwap(onlyHookless, _exactOutParams(wantOut, type(uint128).max));
        vm.revertToState(snapshotId);

        // Exact-out is judged on the input side: the chosen route must not cost more than
        // the hookless baseline would have.
        assertApproxEqRel(spentBoth, spentHookless, 1e15, "exact-out did not pick the cheaper route");
    }

    function test_exactOut_maxInIsEnforced() public {
        uint256 wantOut = 1e14;
        Candidate[] memory cands = new Candidate[](1);
        cands[0] = singleHop(hooklessKey, true);

        // A maxIn of 1 wei cannot possibly buy 1e14 out. The error carries what the route
        // would actually have cost, so the caller learns the real price rather than just
        // that their bound was missed. Hence try/catch rather than `expectRevert`, which
        // would swallow the arguments.
        try sworn.swornSwap(cands, _exactOutParams(wantOut, 1)) returns (uint256) {
            revert("should have reverted on maxIn");
        } catch (bytes memory reason) {
            assertEq(bytes4(reason), SwornRouter.ExcessiveInput.selector, "wrong error");
            (uint256 wouldCost, uint256 maxIn) = abi.decode(_stripSelector(reason), (uint256, uint256));
            assertEq(maxIn, 1, "error did not echo the caller's bound");
            assertGt(wouldCost, maxIn, "error did not report the real cost");
        }
    }

    // -----------------------------------------------------------------------------------
    // multi-hop
    // -----------------------------------------------------------------------------------

    function _twoHop(
        PoolKey memory first,
        PoolKey memory second
    ) internal pure returns (Candidate memory c) {
        // currency0 -> currency1 -> currency0. A contrived round trip, but it exercises
        // the chaining arithmetic without needing a third token.
        c.hops = new Hop[](2);
        c.hops[0] = Hop({key: first, zeroForOne: true, hookData: ""});
        c.hops[1] = Hop({key: second, zeroForOne: false, hookData: ""});
    }

    function test_multiHop_exactIn_chainsAmountsAndSettlesEnds() public {
        // Two hookless-equivalent pools so the round trip only loses fees.
        Candidate[] memory cands = new Candidate[](1);
        cands[0] = _twoHop(hooklessKey, honestKey);

        SwornParams memory p = defaultParams();
        // A round trip ends in the token it started in.
        p.tokenOut = currency0;

        uint256 before = _bal(currency0);
        uint256 out = sworn.swornSwap(cands, p);

        // Two 0.30% fees means the round trip must lose money; the point is that the
        // intermediate leg never surfaces as a balance and the ends settle cleanly.
        assertGt(out, 0, "multi-hop produced nothing");
        assertLt(out, SWAP_AMOUNT, "round trip cannot profit");
        assertEq(_bal(currency0), before - SWAP_AMOUNT + out, "end balances do not reconcile");
        _assertRouterEmpty();
    }

    function test_multiHop_isComparedAgainstSingleHopOnFinalOutput() public {
        vm.txGasPrice(1 gwei);

        Candidate[] memory cands = new Candidate[](2);
        cands[0] = _twoHop(hooklessKey, honestKey); // round trip, ends in currency0
        cands[1] = singleHop(hooklessKey, true); // ends in currency1

        SwornParams memory p = defaultParams();

        // Candidates must be commensurable: routes ending in different currencies are the
        // integrator's error, and the router compares raw probed output. This documents
        // that the SDK is responsible for building a coherent candidate set, which is why
        // Phase 8 derives candidates from the index rather than trusting the caller.
        uint256 out = sworn.swornSwap(cands, p);
        assertGt(out, 0);
        _assertRouterEmpty();
    }

    /// @dev Drop the 4-byte selector so the custom error's arguments can be decoded.
    function _stripSelector(
        bytes memory data
    ) internal pure returns (bytes memory out) {
        out = new bytes(data.length - 4);
        for (uint256 i = 4; i < data.length; i++) {
            out[i - 4] = data[i];
        }
    }

    function test_emptyRouteReverts() public {
        Candidate[] memory cands = new Candidate[](1);
        cands[0].hops = new Hop[](0);

        vm.expectRevert();
        sworn.swornSwap(cands, defaultParams());
    }

    // -----------------------------------------------------------------------------------
    // the safety net
    // -----------------------------------------------------------------------------------

    function test_divergenceRevertsWhenAHookBeatsTheProbe() public {
        // A hook that keeps state the probe's revert cannot roll back quotes free and
        // then charges. Nothing deployable can do this, but if the threat model is ever
        // wrong, this is what must happen: revert, never silent loss.
        (address hook, PoolKey memory key) =
            deployRecordingHookAndPool("CheatingDivergentHook", abi.encode(manager), SKIM_FLAGS, 43);
        assertTrue(hook != address(0));

        Candidate[] memory only = new Candidate[](1);
        only[0] = singleHop(key, true);

        uint256 outBefore = _bal(currency1);

        try sworn.swornSwap(only, defaultParams()) returns (uint256) {
            revert("divergence went undetected");
        } catch (bytes memory reason) {
            assertEq(bytes4(reason), SwornRouter.Divergence.selector, "wrong error");
        }

        // The user is exactly where they started: denial, not theft.
        assertEq(_bal(currency1), outBefore, "user lost funds to a divergent hook");
        _assertRouterEmpty();
    }

    function test_stipendUnavailableWhenProbeGasExceedsWhatIsForwardable() public {
        SwornParams memory p = defaultParams();
        // EIP-150 forwards at most 63/64 of the remaining gas. Asking for more than the
        // transaction will ever have must fail loudly rather than silently forward less,
        // which would let a hook see different gas in the probe and the execution.
        p.probeGas = type(uint64).max;

        Candidate[] memory only = new Candidate[](1);
        only[0] = singleHop(hooklessKey, true);

        try sworn.swornSwap(only, p) returns (uint256) {
            revert("should have refused an unforwardable stipend");
        } catch (bytes memory reason) {
            assertEq(bytes4(reason), SwornRouter.StipendUnavailable.selector, "wrong error");
        }
    }

    function test_tooManyCandidatesReverts() public {
        Candidate[] memory many = new Candidate[](256);
        for (uint256 i = 0; i < many.length; i++) {
            many[i] = singleHop(hooklessKey, true);
        }

        // Candidate indices are uint8 all the way to the `Sworn` event, so the input is
        // bounded rather than allowed to wrap.
        vm.expectRevert(abi.encodeWithSelector(SwornRouter.TooManyCandidates.selector, uint256(256)));
        sworn.swornSwap(many, defaultParams());
    }
}
