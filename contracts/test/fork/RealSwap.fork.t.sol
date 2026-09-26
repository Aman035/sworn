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

/// @notice The end-to-end claim, against real hooks and real tokens on a Base fork.
///
/// @dev The other fork tests assert that the router never retains value, which a revert
///      also satisfies. This one asserts the harder thing: that a swap through a live
///      mainnet hook **completes**, pays out, and passes the divergence check, so the
///      guarantee is not merely a well-defended way of refusing to trade.
///
///      ETH/USDC was chosen deliberately. An earlier version of this test routed into a
///      token at `0xb200...108C` whose entire deployed code is the single byte `0xef`, an
///      invalid opcode: v4 will happily initialize and swap a pool against it, the swap
///      accounts correctly, and then settlement reverts inside `transfer` for every router
///      that has ever existed. Nothing is wrong with the pool; the token cannot execute.
///      A fork test that picks its pools carelessly measures that instead of the router.
contract RealSwapForkTest is Test {
    using PoolIdLibrary for PoolKey;

    IPoolManager internal constant POOL_MANAGER = IPoolManager(0x498581fF718922c3f8e6A244956aF099B2652b2b);

    Currency internal constant ETH = Currency.wrap(address(0));
    Currency internal constant USDC = Currency.wrap(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);

    /// @dev Both carry live ETH/USDC pools and both appear in `divergence.json`.
    address internal constant STATIC_FEE_HOOK = 0x4440854B2d02C57A0Dc5c58b7A884562D875c0c4;
    address internal constant DYNAMIC_FEE_HOOK = 0x9d11f9505CA92f4b6983c1285D1aC0aAFF7eC0c0;

    uint24 internal constant DYNAMIC_FEE_FLAG = 0x800000;
    uint256 internal constant PINNED_BLOCK = 51_700_000;

    SwornRouter internal sworn;
    bool internal live;

    function setUp() public {
        string memory rpc = vm.envOr("BASE_RPC_ARCHIVE", string(""));
        if (bytes(rpc).length == 0) return;
        vm.createSelectFork(rpc, PINNED_BLOCK);
        live = true;
        sworn = new SwornRouter(POOL_MANAGER, ISignatureTransfer(address(0)));
    }

    function _key(
        address hook,
        uint24 fee,
        int24 tickSpacing
    ) internal pure returns (PoolKey memory) {
        return PoolKey({currency0: ETH, currency1: USDC, fee: fee, tickSpacing: tickSpacing, hooks: IHooks(hook)});
    }

    function _usable(
        PoolKey memory key
    ) internal view returns (bool) {
        (uint160 price,,,) = StateLibrary.getSlot0(POOL_MANAGER, key.toId());
        return price != 0 && StateLibrary.getLiquidity(POOL_MANAGER, key.toId()) != 0;
    }

    /// @dev The standard hookless ETH/USDC tiers, tried in order of likely depth. Searching
    ///      rather than hard-coding one keeps the test meaningful if the pinned block moves.
    function _hooklessKey() internal view returns (PoolKey memory found, bool ok) {
        uint24[4] memory fees = [uint24(500), 3000, 100, 10000];
        int24[4] memory spacings = [int24(10), 60, 1, 200];
        for (uint256 i = 0; i < fees.length; i++) {
            PoolKey memory candidate = _key(address(0), fees[i], spacings[i]);
            if (_usable(candidate)) return (candidate, true);
        }
        return (found, false);
    }

    function test_completesASwapThroughALiveHook() public {
        vm.skip(!live);

        PoolKey memory hooked = _key(STATIC_FEE_HOOK, 90, 2);
        (PoolKey memory hookless, bool haveHookless) = _hooklessKey();
        vm.skip(!_usable(hooked) || !haveHookless);

        Candidate[] memory cands = new Candidate[](2);
        cands[0].hops = new Hop[](1);
        cands[0].hops[0] = Hop({key: hooked, zeroForOne: true, hookData: ""});
        cands[1].hops = new Hop[](1);
        cands[1].hops[0] = Hop({key: hookless, zeroForOne: true, hookData: ""});

        uint256 amountIn = 0.05 ether;
        deal(address(this), 1 ether);

        // A real gas price, so anything the hook keys on `tx.gasprice` is armed. The probe
        // runs in this same transaction and sees the same value.
        vm.txGasPrice(12_000_000);

        uint256 before = IERC20Minimal(Currency.unwrap(USDC)).balanceOf(address(this));
        uint256 out = sworn.swornSwap{value: amountIn}(cands, _params(amountIn));
        uint256 delivered = IERC20Minimal(Currency.unwrap(USDC)).balanceOf(address(this)) - before;

        console.log("delivered USDC:", delivered);
        console.log("reported out  :", out);

        assertGt(out, 0, "router reported no output");
        // The router's return value is the user's money, so it must be the money that moved
        //, not an internal figure that happens to be positive.
        assertEq(delivered, out, "reported output does not match tokens received");
        assertEq(address(sworn).balance, 0, "router retained native value");
        assertEq(IERC20Minimal(Currency.unwrap(USDC)).balanceOf(address(sworn)), 0, "router retained USDC");
    }

    function test_completesThroughADynamicFeeHook() public {
        vm.skip(!live);

        PoolKey memory hooked = _key(DYNAMIC_FEE_HOOK, DYNAMIC_FEE_FLAG, 10);
        vm.skip(!_usable(hooked));

        Candidate[] memory cands = new Candidate[](1);
        cands[0].hops = new Hop[](1);
        cands[0].hops[0] = Hop({key: hooked, zeroForOne: true, hookData: ""});

        uint256 amountIn = 0.05 ether;
        deal(address(this), 1 ether);
        vm.txGasPrice(12_000_000);

        uint256 before = IERC20Minimal(Currency.unwrap(USDC)).balanceOf(address(this));
        uint256 out = sworn.swornSwap{value: amountIn}(cands, _params(amountIn));

        // A dynamic-fee hook picks the fee inside `beforeSwap`, so the probe and the
        // execution each ask it fresh. Equal deltas here mean it answered the same twice.
        assertGt(out, 0, "no output through dynamic-fee hook");
        assertEq(
            IERC20Minimal(Currency.unwrap(USDC)).balanceOf(address(this)) - before,
            out,
            "dynamic-fee route paid out a different amount than it reported"
        );
    }

    function test_soleCandidateStillPassesTheDivergenceCheck() public {
        vm.skip(!live);

        (PoolKey memory hookless, bool ok) = _hooklessKey();
        vm.skip(!ok);

        Candidate[] memory cands = new Candidate[](1);
        cands[0].hops = new Hop[](1);
        cands[0].hops[0] = Hop({key: hookless, zeroForOne: true, hookData: ""});

        uint256 amountIn = 0.05 ether;
        deal(address(this), 1 ether);
        vm.txGasPrice(12_000_000);

        // With one honest candidate the probe and the execution must agree exactly; if this
        // ever reverts with Divergence the router is wrong, not the pool.
        uint256 out = sworn.swornSwap{value: amountIn}(cands, _params(amountIn));
        assertGt(out, 0, "hookless route delivered nothing");
    }

    function _params(
        uint256 amountIn
    ) internal view returns (SwornParams memory) {
        return SwornParams({
            tokenIn: ETH,
            tokenOut: USDC,
            amountSpecified: -int256(amountIn),
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

    receive() external payable {}
}
