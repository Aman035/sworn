// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {console2 as console} from "forge-std/console2.sol";

import {ISignatureTransfer} from "permit2/src/interfaces/ISignatureTransfer.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {StateLibrary} from "v4-core/src/libraries/StateLibrary.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolId, PoolIdLibrary} from "v4-core/src/types/PoolId.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {Candidate, Hop, SwornParams, SwornRouter} from "../../src/SwornRouter.sol";

/// @notice Sworn against the hooks 0x named, on a fork of Base.
///
/// @dev The fixtures in `test/unit` model attacks we designed. These are the real
///      deployed contracts from the 14 Sep 2026 report, on the real pool, at a pinned
///      block, which is the only way to find out whether the mechanism survives contact
///      with code nobody in this repo wrote.
///
///      Skips rather than fails when `BASE_RPC_ARCHIVE` is unset, so the default `forge
///      test` stays runnable offline.
contract NamedHooksForkTest is Test {
    using PoolIdLibrary for PoolKey;

    IPoolManager internal constant POOL_MANAGER = IPoolManager(0x498581fF718922c3f8e6A244956aF099B2652b2b);

    /// @dev "ETH/NVDAc", median fee when charged 18%, $143,037 charged (0x, 14 Sep 2026).
    address internal constant NAMED_HOOK = 0x800CEF53c3Fd41109dFfeC62E5251BDD7Acba5c7;
    Currency internal constant ETH = Currency.wrap(address(0));
    Currency internal constant TOKEN = Currency.wrap(0xb20000000000000000000078ee7ce2fE4908108C);

    // Pinned so the numbers are reproducible. Inside the 30-day fills window where the
    // census recorded 1,088 fills for this pool.
    uint256 internal constant PINNED_BLOCK = 51_700_000;

    SwornRouter internal sworn;
    PoolKey internal toxicKey;
    PoolKey internal hooklessKey;

    bool internal live;

    function setUp() public {
        string memory rpc = vm.envOr("BASE_RPC_ARCHIVE", string(""));
        if (bytes(rpc).length == 0) return;
        vm.createSelectFork(rpc, PINNED_BLOCK);
        live = true;

        sworn = new SwornRouter(POOL_MANAGER, ISignatureTransfer(address(0)));

        // The hook's own pool: dynamic fee, tick spacing 2.
        toxicKey = PoolKey({currency0: ETH, currency1: TOKEN, fee: 0x800000, tickSpacing: 2, hooks: IHooks(NAMED_HOOK)});

        // The most liquid *hookless* pool for this pair at the pinned block. Chosen by
        // reading on-chain liquidity, not by picking the lowest fee: of the 17 hookless
        // pools our census found for this pair, only 5 have any liquidity at all, and the
        // cheapest (fee 75) has none. A candidate set built from fee tiers alone would
        // hand the router routes that cannot trade.
        hooklessKey =
            PoolKey({currency0: ETH, currency1: TOKEN, fee: 100_000, tickSpacing: 1000, hooks: IHooks(address(0))});
    }

    function _liquidity(
        PoolKey memory key
    ) internal view returns (uint128) {
        return StateLibrary.getLiquidity(POOL_MANAGER, key.toId());
    }

    function test_censusPoolsExistOnChain() public {
        vm.skip(!live);
        // Confirms the census reconstructed real PoolKeys: a wrong key hashes to a pool
        // id that has never been initialized, and slot0 would read zero.
        (uint160 toxicPrice,,,) = StateLibrary.getSlot0(POOL_MANAGER, toxicKey.toId());
        (uint160 hooklessPrice,,,) = StateLibrary.getSlot0(POOL_MANAGER, hooklessKey.toId());

        console.log("toxic pool    sqrtPriceX96:", toxicPrice);
        console.log("toxic pool    liquidity   :", _liquidity(toxicKey));
        console.log("hookless pool sqrtPriceX96:", hooklessPrice);
        console.log("hookless pool liquidity   :", _liquidity(hooklessKey));

        assertGt(toxicPrice, 0, "the hook's pool is not initialized at this block");
    }

    function test_swornRoutesBetweenRealCandidates() public {
        vm.skip(!live);
        (uint160 toxicPrice,,,) = StateLibrary.getSlot0(POOL_MANAGER, toxicKey.toId());
        (uint160 hooklessPrice,,,) = StateLibrary.getSlot0(POOL_MANAGER, hooklessKey.toId());
        vm.skip(toxicPrice == 0 || hooklessPrice == 0);
        vm.skip(_liquidity(toxicKey) == 0 && _liquidity(hooklessKey) == 0);

        Candidate[] memory cands = new Candidate[](2);
        cands[0].hops = new Hop[](1);
        cands[0].hops[0] = Hop({key: toxicKey, zeroForOne: true, hookData: ""});
        cands[1].hops = new Hop[](1);
        cands[1].hops[0] = Hop({key: hooklessKey, zeroForOne: true, hookData: ""});

        uint256 amountIn = 0.01 ether;
        deal(address(this), 10 ether);

        SwornParams memory p = SwornParams({
            tokenIn: ETH,
            tokenOut: TOKEN,
            amountSpecified: -int256(amountIn),
            minOut: 0,
            hookMarginBps: 0,
            probeGas: 3_000_000,
            maxProbes: 4,
            recipient: address(this),
            deadline: type(uint256).max,
            usePermit2: false,
            permit: ""
        });

        // A real gas price, so any environment sniffing on this hook is armed.
        vm.txGasPrice(10_000_000);

        try sworn.swornSwap{value: amountIn}(cands, p) returns (uint256 out) {
            console.log("swornSwap delivered:", out);
            assertGt(out, 0, "no output");
            // Whatever the hook did, the executed amount equalled the probed amount or
            // the router would have reverted with Divergence.
            assertEq(address(sworn).balance, 0, "router retained native value");
        } catch (bytes memory reason) {
            // A revert is an acceptable outcome and an informative one: it means every
            // candidate was unavailable or the hook griefed the probe. What must never
            // happen is a silent underfill.
            console.log("swornSwap reverted; selector:");
            console.logBytes4(bytes4(reason));
            assertEq(address(sworn).balance, 0, "router retained native value after revert");
        }
    }

    receive() external payable {}
}
