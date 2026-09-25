// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {console2 as console} from "forge-std/Test.sol";

import {Candidate, SwornParams, SwornRouter} from "../../src/SwornRouter.sol";
import {SwornTestBase} from "./SwornTestBase.sol";

/// @notice The central claim: a hook cannot show one price and deliver another, because
///         Sworn probes inside the same transaction that executes.
contract SwornRouterTest is SwornTestBase {
    function setUp() public {
        setUpSworn();
    }

    function _balanceOut() internal view returns (uint256) {
        return IERC20Minimal(Currency.unwrap(currency1)).balanceOf(address(this));
    }

    // -----------------------------------------------------------------------------------
    // baseline
    // -----------------------------------------------------------------------------------

    function test_singleHooklessPool_executesAndDeliversProbedAmount() public {
        Candidate[] memory cands = new Candidate[](1);
        cands[0] = singleHop(hooklessKey, true);

        uint256 before = _balanceOut();
        uint256 out = sworn.swornSwap(cands, defaultParams());

        assertGt(out, 0, "no output");
        assertEq(_balanceOut() - before, out, "delivered amount differs from reported");
    }

    function test_honestHook_isUsableJustLikeAHooklessPool() public {
        (, PoolKey memory honest) = deployHookAndPool("HonestHook", abi.encode(manager), SKIM_FLAGS, 1);

        Candidate[] memory cands = new Candidate[](1);
        cands[0] = singleHop(honest, true);

        uint256 before = _balanceOut();
        uint256 out = sworn.swornSwap(cands, defaultParams());

        assertGt(out, 0);
        assertEq(_balanceOut() - before, out);
    }

    // -----------------------------------------------------------------------------------
    // the guarantee
    // -----------------------------------------------------------------------------------

    function test_gaspriceSniffHook_losesTheRouteToTheHooklessPool() public {
        (, PoolKey memory toxic) = deployHookAndPool("GaspriceSniffHook", abi.encode(manager), SKIM_FLAGS, 2);

        // A real transaction has a non-zero gas price, so the hook charges 18%.
        vm.txGasPrice(1 gwei);

        Candidate[] memory cands = candidates(toxic, hooklessKey, true);

        uint256 before = _balanceOut();
        uint256 out = sworn.swornSwap(cands, defaultParams());
        uint256 delivered = _balanceOut() - before;

        assertEq(delivered, out, "delivered != reported");

        // What the hookless pool alone would have paid: the toxic route must not beat it.
        uint256 hooklessOnly = _hooklessOutput();
        assertApproxEqRel(out, hooklessOnly, 1e15, "did not route to the hookless pool");
    }

    function test_quoteAtZeroGasPriceLooksBetter_whichIsTheWholeAttack() public {
        (, PoolKey memory toxic) = deployHookAndPool("GaspriceSniffHook", abi.encode(manager), SKIM_FLAGS, 3);

        Candidate[] memory onlyToxic = new Candidate[](1);
        onlyToxic[0] = singleHop(toxic, true);

        // Simulated: gas price 0, hook charges nothing.
        vm.txGasPrice(0);
        uint256 snapshotId = vm.snapshotState();
        uint256 simulated = sworn.swornSwap(onlyToxic, defaultParams());
        vm.revertToState(snapshotId);

        // Executed: real gas price, hook charges 18%.
        vm.txGasPrice(1 gwei);
        uint256 executed = sworn.swornSwap(onlyToxic, defaultParams());

        assertGt(simulated, executed, "fixture does not actually spoof");
        // The gap is the attack, and it is large enough to matter.
        assertGt((simulated - executed) * 10_000 / simulated, 1_000, "spoof gap under 10%");
    }

    function _hooklessOutput() internal returns (uint256) {
        uint256 snapshotId = vm.snapshotState();
        Candidate[] memory only = new Candidate[](1);
        only[0] = singleHop(hooklessKey, true);
        uint256 out = sworn.swornSwap(only, defaultParams());
        vm.revertToState(snapshotId);
        return out;
    }

    /// @notice Prints the spoof gap and what Sworn recovers, so the README number has a
    ///         reproducible source rather than a rounded anecdote.
    function test_reportSpoofGapAndRecovery() public {
        (, PoolKey memory toxic) = deployHookAndPool("GaspriceSniffHook", abi.encode(manager), SKIM_FLAGS, 9);

        Candidate[] memory onlyToxic = new Candidate[](1);
        onlyToxic[0] = singleHop(toxic, true);

        vm.txGasPrice(0);
        uint256 snapQuote = vm.snapshotState();
        uint256 quoted = sworn.swornSwap(onlyToxic, defaultParams());
        vm.revertToState(snapQuote);

        vm.txGasPrice(1 gwei);
        uint256 snapNaive = vm.snapshotState();
        uint256 naive = sworn.swornSwap(onlyToxic, defaultParams());
        vm.revertToState(snapNaive);

        Candidate[] memory both = candidates(toxic, hooklessKey, true);
        uint256 protectedOut = sworn.swornSwap(both, defaultParams());

        console.log("quoted at gasprice=0      ", quoted);
        console.log("delivered if forced toxic ", naive);
        console.log("delivered through Sworn   ", protectedOut);
        console.log("spoof gap bps             ", (quoted - naive) * 10_000 / quoted);
        console.log("recovered bps             ", (protectedOut - naive) * 10_000 / naive);

        assertGt(protectedOut, naive, "Sworn did not improve on the toxic route");
    }
}
