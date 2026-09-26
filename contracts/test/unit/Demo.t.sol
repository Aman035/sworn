// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {console2 as console} from "forge-std/console2.sol";

import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {HookBook} from "../../src/HookBook.sol";
import {NaiveRouter} from "../fixtures/NaiveRouter.sol";
import {SwornTestBase} from "./SwornTestBase.sol";

/// @notice The demo, as an executable script rather than a recording.
///
/// @dev `docs/DEMO.md` storyboards this; `scripts/demo.sh` runs it. Every number printed
///      below is produced live by the EVM during the run. There is no narration string
///      containing a figure, because a demo whose numbers are typed in is a slideshow.
///
///      It is written as a test so that the demo cannot rot: if the story stops being
///      true, CI fails. The assertions are the story.
contract DemoTest is SwornTestBase {
    NaiveRouter internal naive;
    HookBook internal book;

    uint256 internal constant BPS = 10_000;

    function setUp() public {
        setUpSworn();
        naive = new NaiveRouter(manager);
        IERC20Minimal(Currency.unwrap(currency0)).approve(address(naive), type(uint256).max);
        book = new HookBook(address(this));
        book.setAttestor(address(this), true);
    }

    function _rule() internal pure {
        console.log("--------------------------------------------------------------");
    }

    function test_demo() public {
        _rule();
        console.log("SWORN DEMO -- a hook that quotes one price and charges another");
        _rule();

        // ---------------------------------------------------------------- act 1
        console.log("");
        console.log("ACT 1  Two pools for the same pair.");
        (address toxicHook, PoolKey memory toxic) =
            deployHookAndPool("GaspriceSniffHook", abi.encode(manager), SKIM_FLAGS, 901);
        console.log("  pool A  hookless, the honest baseline");
        console.log("  pool B  hooked by GaspriceSniffHook at", toxicHook);
        console.log("          it reads tx.gasprice: zero means a simulator is asking");

        // ---------------------------------------------------------------- act 2
        console.log("");
        console.log("ACT 2  What a quote sees. tx.gasprice = 0, as in every eth_call.");
        vm.txGasPrice(0);
        uint256 snap = vm.snapshotState();
        uint256 quoted = _naive(toxic);
        vm.revertToState(snap);
        console.log("  pool B quotes:", quoted);

        // ---------------------------------------------------------------- act 3
        console.log("");
        console.log("ACT 3  What a real transaction gets. Same pool, same size.");
        vm.txGasPrice(1 gwei);
        snap = vm.snapshotState();
        uint256 delivered = _naive(toxic);
        vm.revertToState(snap);
        console.log("  pool B delivers:", delivered);

        uint256 takenBps = ((quoted - delivered) * BPS) / quoted;
        console.log("  taken without being quoted (bps):", takenBps);
        assertLt(delivered, quoted, "fixture is not actually spoofing");

        // A router that trusted the quote would have routed here and lost that much.
        assertGt(takenBps, 100, "demo needs a visible spoof to be worth showing");

        // ---------------------------------------------------------------- act 4
        console.log("");
        console.log("ACT 4  Sworn probes both pools inside the transaction that settles.");
        snap = vm.snapshotState();
        uint256 naiveOut = _naive(toxic);
        vm.revertToState(snap);

        uint256 swornOut = sworn.swornSwap(candidates(toxic, hooklessKey, true), defaultParams());
        console.log("  naive router, trusting the quote:", naiveOut);
        console.log("  sworn router, probing in-tx    :", swornOut);
        console.log("  recovered (bps):", ((swornOut - naiveOut) * BPS) / naiveOut);

        assertGt(swornOut, naiveOut, "sworn did not beat the naive route");
        // The probe ran at the same tx.gasprice as the execution, so the hook had no way
        // to answer it differently. That is the whole mechanism.
        assertEq(address(sworn).balance, 0, "router retained value");

        // ---------------------------------------------------------------- act 5
        console.log("");
        console.log("ACT 5  What HookBook says, and what it refuses to say.");
        book.setScore(toxicHook, 82, 0, uint64(block.number), bytes32(uint256(1)));

        bool hasToxic = book.hasScore(toxicHook);
        bool hasUnknown = book.hasScore(address(0xBEEF));
        uint32 unknownFlags = book.flags(address(0xBEEF));

        console.log("  scored hook   hasScore:", hasToxic);
        console.log("                score   :", book.score(toxicHook));
        console.log("                flags   :", book.flags(toxicHook));
        console.log("  unseen hook   hasScore:", hasUnknown);
        console.log("                flags   :", unknownFlags);
        console.log("  an unmeasured hook reads as INSUFFICIENT_DATA, never as a clean 0");

        assertTrue(hasToxic, "scored hook has no score");
        assertFalse(hasUnknown, "an unseen hook must not read as scored");
        assertTrue(unknownFlags != 0, "an unseen hook must not read as flagless");

        console.log("");
        _rule();
        console.log("The quote was a lie. The probe was not, because it was the trade.");
        _rule();
    }

    function _naive(
        PoolKey memory key
    ) internal returns (uint256) {
        // forge-lint: disable-next-line(unsafe-typecast)
        return naive.swap(key, true, -int256(SWAP_AMOUNT), 0, address(this));
    }
}
