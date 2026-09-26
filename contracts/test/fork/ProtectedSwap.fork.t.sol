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
import {NaiveRouter} from "../fixtures/NaiveRouter.sol";

/// @notice One swap that actually happened, replayed both ways.
///
/// @dev Every other test in this repo proves the mechanism against a fixture written to be
///      caught. This one replays a real fill: transaction
///      `0x528ff79b...cc525`, Base block 51,247,545, measured by `b_divergence` as taking
///      640 bps more than the quoter said it would.
///
///      At that block two pools held the same pair. The swapper went through the hooked
///      one and received 16,388,887 USDC units. The hookless pool beside it would have
///      returned 17,438,404, which is $1.05 more on a $16.39 trade.
///
///      A naive router takes the first pool because its quote looked fine. Sworn probes
///      both inside the settling transaction, sees what each actually returns, and takes
///      the better one. The gap is the product.
contract ProtectedSwapForkTest is Test {
    using PoolIdLibrary for PoolKey;

    IPoolManager internal constant POOL_MANAGER = IPoolManager(0x498581fF718922c3f8e6A244956aF099B2652b2b);

    Currency internal constant TOKEN = Currency.wrap(0x5ab000ff9B9FfE0349CE5ffA5fD86f217C3680F5);
    Currency internal constant USDC = Currency.wrap(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);

    address internal constant CHARGING_HOOK = 0xF54473F4C554BaA8411c0A7DAC7DF735f34D00c4;
    uint24 internal constant DYNAMIC_FEE_FLAG = 0x800000;

    /// @dev The block the measured fill settled in.
    uint256 internal constant PINNED_BLOCK = 51_247_545;
    uint256 internal constant AMOUNT_IN = 1_597_858_195_661_697_305_278;

    SwornRouter internal sworn;
    NaiveRouter internal naive;
    PoolKey internal hookedKey;
    PoolKey internal plainKey;
    bool internal live;

    function setUp() public {
        string memory rpc = vm.envOr("BASE_RPC_ARCHIVE", string(""));
        if (bytes(rpc).length == 0) return;
        vm.createSelectFork(rpc, PINNED_BLOCK);
        live = true;

        sworn = new SwornRouter(POOL_MANAGER, ISignatureTransfer(address(0)));
        naive = new NaiveRouter(POOL_MANAGER);

        hookedKey = PoolKey({
            currency0: TOKEN, currency1: USDC, fee: DYNAMIC_FEE_FLAG, tickSpacing: 2, hooks: IHooks(CHARGING_HOOK)
        });
        plainKey = PoolKey({currency0: TOKEN, currency1: USDC, fee: 9000, tickSpacing: 90, hooks: IHooks(address(0))});
    }

    function _usable(
        PoolKey memory key
    ) internal view returns (bool) {
        (uint160 price,,,) = StateLibrary.getSlot0(POOL_MANAGER, key.toId());
        return price != 0 && StateLibrary.getLiquidity(POOL_MANAGER, key.toId()) != 0;
    }

    function _fund() internal {
        deal(Currency.unwrap(TOKEN), address(this), AMOUNT_IN * 2);
        IERC20Minimal(Currency.unwrap(TOKEN)).approve(address(naive), type(uint256).max);
        IERC20Minimal(Currency.unwrap(TOKEN)).approve(address(sworn), type(uint256).max);
    }

    /// @notice Sworn takes the best route actually on offer to it.
    ///
    /// @dev The hook quotes this caller 16,340,546. Rather than accept that, Sworn probes
    ///      the hookless pool beside it, finds 17,438,404, and settles there. It does not
    ///      have to know why the hook is charging it, or even that it is being charged.
    function test_swornRoutesAwayFromTheChargingHook() public {
        vm.skip(!live);
        vm.skip(!_usable(hookedKey) || !_usable(plainKey));
        _fund();
        vm.txGasPrice(12_000_000);

        // What this caller gets if it simply trusts the hooked pool.
        uint256 snap = vm.snapshotState();
        Candidate[] memory onlyHooked = new Candidate[](1);
        onlyHooked[0].hops = new Hop[](1);
        onlyHooked[0].hops[0] = Hop({key: hookedKey, zeroForOne: true, hookData: ""});
        uint256 hookedOut = sworn.swornSwap(onlyHooked, _params());
        vm.revertToState(snap);

        Candidate[] memory both = new Candidate[](2);
        both[0].hops = new Hop[](1);
        both[0].hops[0] = Hop({key: hookedKey, zeroForOne: true, hookData: ""});
        both[1].hops = new Hop[](1);
        both[1].hops[0] = Hop({key: plainKey, zeroForOne: true, hookData: ""});

        uint256 before = IERC20Minimal(Currency.unwrap(USDC)).balanceOf(address(this));
        uint256 swornOut = sworn.swornSwap(both, _params());
        uint256 delivered = IERC20Minimal(Currency.unwrap(USDC)).balanceOf(address(this)) - before;

        console.log("Base block                      ", PINNED_BLOCK);
        console.log("what the hook offered this caller", hookedOut);
        console.log("what Sworn settled for           ", swornOut);
        console.log("recovered, bps                   ", ((swornOut - hookedOut) * 10_000) / hookedOut);

        assertEq(delivered, swornOut, "reported output is not what arrived");
        assertGt(swornOut, hookedOut, "Sworn accepted the charging pool");
        assertEq(IERC20Minimal(Currency.unwrap(USDC)).balanceOf(address(sworn)), 0, "router kept USDC");
    }

    /// @notice The decisive experiment: the same pool, the same block, the same amount,
    ///         reached by two different callers.
    ///
    /// @dev If the hook treated everyone alike these two numbers would match. The trace
    ///      says they do not: `NaiveRouter` is charged a zero fee and nothing in
    ///      `afterSwap`, while `SwornRouter` is charged a 700 fee and the hook transfers
    ///      itself a further slice of the output. This is the router-whitelist pattern
    ///      from THREAT_MODEL.md, on mainnet, at a block where it actually happened.
    function test_theHookChargesByCaller() public {
        vm.skip(!live);
        vm.skip(!_usable(hookedKey));
        _fund();
        vm.txGasPrice(12_000_000);

        uint256 snap = vm.snapshotState();
        uint256 viaNaive = naive.swap(hookedKey, true, -int256(AMOUNT_IN), 0, address(this));
        vm.revertToState(snap);

        // Sworn, with the hooked pool as the only candidate, so there is nothing to route
        // to and the number is purely what the hook gives this caller.
        Candidate[] memory only = new Candidate[](1);
        only[0].hops = new Hop[](1);
        only[0].hops[0] = Hop({key: hookedKey, zeroForOne: true, hookData: ""});
        uint256 viaSworn = sworn.swornSwap(only, _params());

        console.log("same pool, same block, same amount in");
        console.log("  caller A (NaiveRouter) receives", viaNaive);
        console.log("  caller B (SwornRouter) receives", viaSworn);

        if (viaNaive > viaSworn) {
            console.log("  the hook charged caller B more, by bps", ((viaNaive - viaSworn) * 10_000) / viaNaive);
        }

        // The assertion is the finding: this pool does not price the two callers alike.
        assertTrue(viaNaive != viaSworn, "hook treated both callers identically");
    }

    function _params() internal view returns (SwornParams memory) {
        return SwornParams({
            tokenIn: TOKEN,
            tokenOut: USDC,
            amountSpecified: -int256(AMOUNT_IN),
            minOut: 1,
            hookMarginBps: 0,
            probeGas: 3_000_000,
            maxProbes: 4,
            recipient: address(this),
            deadline: type(uint256).max,
            usePermit2: false,
            permit: ""
        });
    }
}
