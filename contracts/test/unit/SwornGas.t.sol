// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {console2 as console} from "forge-std/Test.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {Candidate, SwornParams} from "../../src/SwornRouter.sol";
import {NaiveRouter} from "../fixtures/NaiveRouter.sol";
import {SwornTestBase} from "./SwornTestBase.sol";

/// @notice What the guarantee costs.
///
/// @dev Deliberately free of `vm.txGasPrice`: gas instrumentation interacts with it, and a
///      benchmark that silently stops exercising the thing it measures is worse than no
///      benchmark. Every pool here is honest, so the numbers are pure routing overhead.
contract SwornGasTest is SwornTestBase {
    NaiveRouter internal naive;
    PoolKey internal honestA;
    PoolKey internal honestB;

    function setUp() public {
        setUpSworn();
        naive = new NaiveRouter(manager);
        _approveNaive();
        (, honestA) = deployHookAndPool("HonestHook", abi.encode(manager), SKIM_FLAGS, 51);
        (, honestB) = deployHookAndPool("HonestHook", abi.encode(manager), SKIM_FLAGS, 52);
    }

    function _approveNaive() private {
        (bool a,) = Currency.unwrap(currency0).call(
            abi.encodeWithSignature("approve(address,uint256)", address(naive), type(uint256).max)
        );
        (bool b,) = Currency.unwrap(currency1).call(
            abi.encodeWithSignature("approve(address,uint256)", address(naive), type(uint256).max)
        );
        require(a && b, "approve failed");
    }

    function _candidates(uint256 n) internal view returns (Candidate[] memory out) {
        PoolKey[3] memory keys = [hooklessKey, honestA, honestB];
        out = new Candidate[](n);
        for (uint256 i = 0; i < n; i++) {
            out[i] = singleHop(keys[i], true);
        }
    }

    function test_gasTable() public {
        uint256 snap = vm.snapshotState();
        uint256 baseline = gasleft();
        naive.swap(hooklessKey, true, -int256(SWAP_AMOUNT), 0, address(this));
        baseline -= gasleft();
        vm.revertToState(snap);

        console.log("baseline (NaiveRouter, 1 pool, no probe):", baseline);

        for (uint256 n = 1; n <= 3; n++) {
            uint256 id = vm.snapshotState();
            uint256 used = gasleft();
            sworn.swornSwap(_candidates(n), defaultParams());
            used -= gasleft();
            vm.revertToState(id);

            console.log("swornSwap candidates:", n);
            console.log("   gas:", used);
            console.log("   overhead vs naive:", used > baseline ? used - baseline : 0);
        }

        assertGt(baseline, 0, "baseline did not execute");
    }

    /// @dev Overhead must scale with the number of candidates and no faster: each extra
    ///      candidate is one more probe, not a re-run of the whole route.
    function test_overheadScalesLinearlyInCandidates() public {
        uint256[4] memory used;
        for (uint256 n = 1; n <= 3; n++) {
            uint256 id = vm.snapshotState();
            uint256 before = gasleft();
            sworn.swornSwap(_candidates(n), defaultParams());
            used[n] = before - gasleft();
            vm.revertToState(id);
        }

        uint256 firstStep = used[2] - used[1];
        uint256 secondStep = used[3] - used[2];

        assertGt(used[2], used[1], "second candidate was free");
        assertGt(used[3], used[2], "third candidate was free");
        // Allow a wide band — the point is that it is not super-linear.
        assertLt(secondStep, firstStep * 2, "per-candidate cost is growing");
    }
}
