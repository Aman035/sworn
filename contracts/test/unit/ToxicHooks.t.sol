// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {Candidate, SwornParams, SwornRouter} from "../../src/SwornRouter.sol";
import {NaiveRouter} from "../fixtures/NaiveRouter.sol";
import {SwornTestBase} from "./SwornTestBase.sol";

interface IOwnerSwitch {
    function setFeeBps(
        uint256
    ) external;
    function switchCount() external view returns (uint256);
}

interface IGasSniff {
    function firstGasSeen() external view returns (uint256);
    function lastGasSeen() external view returns (uint256);
    function observations() external view returns (uint256);
}

interface ICallbackSniff {
    function firstResponseHash() external view returns (bytes32);
    function lastResponse() external view returns (bytes memory);
    function observations() external view returns (uint256);
}

interface IRecording {
    function observations() external view returns (string[] memory);
}

interface ICounter {
    function counter() external view returns (uint256);
}

/// @notice One test per attacker capability in `docs/THREAT_MODEL.md`.
contract ToxicHooksTest is SwornTestBase {
    NaiveRouter internal naive;

    function setUp() public {
        setUpSworn();
        naive = new NaiveRouter(manager);
        IERC20Minimal(Currency.unwrap(currency0)).approve(address(naive), type(uint256).max);
        IERC20Minimal(Currency.unwrap(currency1)).approve(address(naive), type(uint256).max);
    }

    function _out() internal view returns (uint256) {
        return IERC20Minimal(Currency.unwrap(currency1)).balanceOf(address(this));
    }

    function _swornBoth(
        PoolKey memory toxic
    ) internal returns (uint256) {
        return sworn.swornSwap(candidates(toxic, hooklessKey, true), defaultParams());
    }

    function _naiveThrough(
        PoolKey memory key
    ) internal returns (uint256) {
        return naive.swap(key, true, -int256(SWAP_AMOUNT), 0, address(this));
    }

    /// @dev The shape of every capability test: the naive router takes the toxic route
    ///      and loses; Sworn probes, sees the truth, and routes around it.
    function _assertSwornBeatsNaive(
        PoolKey memory toxic,
        string memory what
    ) internal {
        uint256 snapshotId = vm.snapshotState();
        uint256 naiveOut = _naiveThrough(toxic);
        vm.revertToState(snapshotId);

        uint256 swornOut = _swornBoth(toxic);

        assertGt(swornOut, naiveOut, what);
    }

    // -----------------------------------------------------------------------------------
    // 1-3: environment sniffing
    // -----------------------------------------------------------------------------------

    function test_originSniff_swornRoutesAround() public {
        (, PoolKey memory toxic) =
            deployHookAndPool("OriginSniffHook", abi.encode(manager, address(0xdead)), SKIM_FLAGS, 11);
        vm.txGasPrice(1 gwei);
        // A real user, not the whitelisted origin.
        // `prank(sender, origin)` is how a real user's tx.origin is simulated; forge has
        // no standalone txOrigin cheatcode.
        vm.startPrank(address(this), address(0xbeef));
        _assertSwornBeatsNaive(toxic, "origin sniffer was not avoided");
        vm.stopPrank();
    }

    function test_coinbaseBasefeeSniff_swornRoutesAround() public {
        (, PoolKey memory toxic) = deployHookAndPool("CoinbaseBasefeeSniffHook", abi.encode(manager), SKIM_FLAGS, 12);
        // A real block has both set; a simulator commonly leaves them zero.
        vm.coinbase(address(0x1234));
        vm.fee(1 gwei);
        _assertSwornBeatsNaive(toxic, "coinbase/basefee sniffer was not avoided");
    }

    // -----------------------------------------------------------------------------------
    // 4-5: nondeterminism
    // -----------------------------------------------------------------------------------

    function test_diceRollBlock_probeSeesTheSameRollAsExecution() public {
        (, PoolKey memory toxic) = deployHookAndPool("DiceRollBlockHook", abi.encode(manager), SKIM_FLAGS, 13);

        // Force the toxic branch: prevrandao is identical for probe and execution because
        // they are in the same block, so the probe sees the real outcome.
        vm.prevrandao(bytes32(uint256(1)));
        _assertSwornBeatsNaive(toxic, "dice-roll (block) was not avoided on a toxic roll");
    }

    function test_diceRollBlock_isChosenWhenTheRollIsHonest() public {
        (, PoolKey memory toxic) = deployHookAndPool("DiceRollBlockHook", abi.encode(manager), SKIM_FLAGS, 14);

        // An even roll means no fee at all. Sworn must not blacklist the hook — it has no
        // opinion about hooks, only about probed outputs.
        vm.prevrandao(bytes32(uint256(2)));

        uint256 out = _swornBoth(toxic);
        uint256 snapshotId = vm.snapshotState();
        uint256 hooklessOnly = sworn.swornSwap(_only(hooklessKey), defaultParams());
        vm.revertToState(snapshotId);

        assertGe(out, hooklessOnly, "an honest roll should not be penalised");
    }

    function test_diceRollCounter_probeRevertRollsTheCounterBack() public {
        (address hook, PoolKey memory toxic) =
            deployHookAndPool("DiceRollCounterHook", abi.encode(manager), SKIM_FLAGS, 15);

        assertEq(ICounter(hook).counter(), 0, "counter should start at zero");

        _swornBoth(toxic);

        // The probe incremented the counter and then reverted; only the executed route's
        // increment survives. If probe state leaked, this would be 2 or more.
        assertLe(ICounter(hook).counter(), 1, "probe state leaked into execution");
    }

    // -----------------------------------------------------------------------------------
    // 6: operator control
    // -----------------------------------------------------------------------------------

    function test_ownerSwitch_swornRoutesAroundWhileToxic() public {
        (address hook, PoolKey memory toxic) = deployHookAndPool("OwnerSwitchHook", abi.encode(manager), SKIM_FLAGS, 16);

        IOwnerSwitch(hook).setFeeBps(1_800);
        assertEq(IOwnerSwitch(hook).switchCount(), 1);

        _assertSwornBeatsNaive(toxic, "owner-switched hook was not avoided");
    }

    function test_ownerSwitch_isUsableAgainOnceTurnedOff() public {
        (address hook, PoolKey memory toxic) = deployHookAndPool("OwnerSwitchHook", abi.encode(manager), SKIM_FLAGS, 17);

        IOwnerSwitch(hook).setFeeBps(1_800);
        IOwnerSwitch(hook).setFeeBps(0);

        // Sworn judges the probe, not the history: a hook that stopped charging is simply
        // a hook that now prices well.
        uint256 out = _swornBoth(toxic);
        assertGt(out, 0);
    }

    // -----------------------------------------------------------------------------------
    // 7: caller discrimination
    // -----------------------------------------------------------------------------------

    function test_routerWhitelist_toxicToSworn_isAvoided() public {
        (, PoolKey memory toxic) =
            deployHookAndPool("RouterWhitelistHook", abi.encode(manager, address(0xfeed)), SKIM_FLAGS, 18);
        _assertSwornBeatsNaive(toxic, "router-whitelist hook was not avoided");
    }

    function test_routerWhitelist_honestToSworn_isUsed() public {
        (, PoolKey memory toxic) =
            deployHookAndPool("RouterWhitelistHook", abi.encode(manager, address(sworn)), SKIM_FLAGS, 19);

        // The hook treats Sworn honestly. Consistent behaviour is safe behaviour: the
        // probe sees the same price the execution delivers, so the route is legitimate.
        uint256 out = _swornBoth(toxic);
        uint256 snapshotId = vm.snapshotState();
        uint256 hooklessOnly = sworn.swornSwap(_only(hooklessKey), defaultParams());
        vm.revertToState(snapshotId);

        assertGe(out, hooklessOnly, "honest-to-Sworn hook should be usable");
    }

    // -----------------------------------------------------------------------------------
    // 8-9: probing the router itself
    // -----------------------------------------------------------------------------------

    function test_gasSniff_probeStateIsRolledBack() public {
        (address hook, PoolKey memory toxic) = deployHookAndPool("GasSniffHook", abi.encode(manager), SKIM_FLAGS, 20);

        _swornBoth(toxic);

        // The hook ran twice — once probed, once executed — but the probe reverted, so
        // its own bookkeeping shows a single invocation. A hook literally cannot count
        // how many times it has been probed, which is the guarantee stated in
        // docs/THREAT_MODEL.md, observed from the attacker's side.
        assertEq(IGasSniff(hook).observations(), 1, "probe bookkeeping leaked into execution");
    }

    function test_gasSniff_probeAndExecutionSeeEqualGas() public {
        (address hook, PoolKey memory toxic) =
            deployRecordingHookAndPool("RecordingGasSniffHook", abi.encode(manager), SKIM_FLAGS, 25);

        _swornBoth(toxic);

        string[] memory seen = IRecording(hook).observations();
        assertGe(seen.length, 2, "hook should have been probed and executed");
        assertEq(
            keccak256(bytes(seen[0])),
            keccak256(bytes(seen[seen.length - 1])),
            // Measured identical at 1,932,728 gas for both calls, so the stipend
            // arithmetic in SwornRouter._assertStipend holds in practice, not just on
            // paper. If EIP-150's 63/64 rule ever bit, these two would diverge.
            "gasleft() at hook entry differed between probe and execution"
        );
    }

    function test_callbackSniff_routerLooksIdenticalInBothPhases() public {
        (address hook, PoolKey memory toxic) =
            deployRecordingHookAndPool("RecordingCallbackSniffHook", abi.encode(manager), SKIM_FLAGS, 26);

        _swornBoth(toxic);

        string[] memory seen = IRecording(hook).observations();
        assertGe(seen.length, 2, "hook should have been probed and executed");
        assertEq(
            keccak256(bytes(seen[0])),
            keccak256(bytes(seen[seen.length - 1])),
            "router answered differently during the probe than during execution"
        );
    }

    // -----------------------------------------------------------------------------------
    // 10-11: griefing
    // -----------------------------------------------------------------------------------

    function test_revertGrief_candidateIsSkippedAndTheSwapStillSucceeds() public {
        (, PoolKey memory griefer) = deployHookAndPool("RevertGriefHook", abi.encode(manager), OBSERVE_FLAGS, 22);

        vm.txGasPrice(1 gwei);

        // Naive routing into this pool simply fails, wasting the user's gas.
        uint256 snapshotId = vm.snapshotState();
        vm.expectRevert();
        _naiveThrough(griefer);
        vm.revertToState(snapshotId);

        // Sworn catches the probe revert, marks the candidate unavailable and routes on.
        uint256 out = _swornBoth(griefer);
        assertGt(out, 0, "griefer should not be able to block the swap");
    }

    function test_gasBurn_probeIsBoundedByTheStipend() public {
        (, PoolKey memory burner) = deployHookAndPool("GasBurnHook", abi.encode(manager), OBSERVE_FLAGS, 23);

        // An out-of-gas probe must be indistinguishable from any other failed candidate.
        uint256 out = _swornBoth(burner);
        assertGt(out, 0, "gas burner should not be able to block the swap");
    }

    function test_allCandidatesUnavailable_revertsWithNoRoute() public {
        (, PoolKey memory griefer) = deployHookAndPool("RevertGriefHook", abi.encode(manager), OBSERVE_FLAGS, 24);

        vm.txGasPrice(1 gwei);

        Candidate[] memory only = new Candidate[](1);
        only[0] = singleHop(griefer, true);

        vm.expectRevert(SwornRouter.NoRoute.selector);
        sworn.swornSwap(only, defaultParams());
    }

    function _only(
        PoolKey memory key
    ) internal pure returns (Candidate[] memory out) {
        out = new Candidate[](1);
        out[0] = singleHop(key, true);
    }
}
