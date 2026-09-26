// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {console2 as console} from "forge-std/console2.sol";

import {ISignatureTransfer} from "permit2/src/interfaces/ISignatureTransfer.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {StateLibrary} from "v4-core/src/libraries/StateLibrary.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolIdLibrary} from "v4-core/src/types/PoolId.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {Candidate, Hop, SwornParams, SwornRouter} from "../../src/SwornRouter.sol";

/// @notice The second hook 0x named, on a fork of BNB Smart Chain.
///
/// @dev USDT/WBNB, fee range 0-12.8%, $18,592 charged (0x, 14 Sep 2026). Unlike the Base
///      hook, this one carries **no returns-delta permission**: its address bits are
///      0x0880 (BEFORE_ADD_LIQUIDITY | BEFORE_SWAP), so it can only override the fee.
///      Two different mechanisms, which is why a census that counts returns-delta hooks
///      as "the dangerous ones" would miss this one entirely.
contract BnbNamedHookForkTest is Test {
    using PoolIdLibrary for PoolKey;

    IPoolManager internal constant POOL_MANAGER = IPoolManager(0x28e2Ea090877bF75740558f6BFB36A5ffeE9e9dF);
    address internal constant NAMED_HOOK = 0x141984423d1a28242B3DD8888C5B0dAa7B13C880;

    Currency internal constant USDT = Currency.wrap(0x55d398326f99059fF775485246999027B3197955);
    Currency internal constant WBNB = Currency.wrap(0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c);

    uint256 internal constant PINNED_BLOCK = 123_900_000;

    SwornRouter internal sworn;
    PoolKey internal toxicKey;
    bool internal live;

    function setUp() public {
        string memory rpc = vm.envOr("BNB_RPC_ARCHIVE", string(""));
        if (bytes(rpc).length == 0) return;
        vm.createSelectFork(rpc, PINNED_BLOCK);
        live = true;

        sworn = new SwornRouter(POOL_MANAGER, ISignatureTransfer(address(0)));
        toxicKey = PoolKey({currency0: USDT, currency1: WBNB, fee: 0x800000, tickSpacing: 2, hooks: IHooks(NAMED_HOOK)});
    }

    function test_censusKeyMatchesAnInitializedPool() public {
        vm.skip(!live);
        (uint160 price,,,) = StateLibrary.getSlot0(POOL_MANAGER, toxicKey.toId());
        uint128 liquidity = StateLibrary.getLiquidity(POOL_MANAGER, toxicKey.toId());

        console.log("BNB named hook pool sqrtPriceX96:", price);
        console.log("BNB named hook pool liquidity   :", liquidity);

        // A PoolKey reconstructed wrongly hashes to a pool that was never initialized.
        assertGt(price, 0, "census key does not correspond to a live pool");
    }

    function test_hookHasNoReturnsDeltaPermission() public {
        vm.skip(!live);
        // Address bits are the permissions in v4. 0x0880 = BEFORE_ADD_LIQUIDITY | BEFORE_SWAP.
        uint160 bits = uint160(NAMED_HOOK) & 0x3FFF;
        assertEq(bits, 0x0880, "permission bits changed");

        uint160 beforeSwapReturnsDelta = 1 << 3;
        uint160 afterSwapReturnsDelta = 1 << 2;
        assertEq(bits & (beforeSwapReturnsDelta | afterSwapReturnsDelta), 0, "unexpected delta permission");

        // So any value it takes has to come through the dynamic fee, which is exactly
        // what 0x reported: a fee range of 0-12.8% rather than a skimmed delta.
        assertEq(toxicKey.fee, 0x800000, "pool is not dynamic-fee");
    }

    receive() external payable {}
}
