// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {ISignatureTransfer} from "permit2/src/interfaces/ISignatureTransfer.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {Deployers} from "v4-core/test/utils/Deployers.sol";

import {Candidate, Hop, SwornParams, SwornRouter} from "../../src/SwornRouter.sol";
import {ModifyLiquidityParams} from "v4-core/src/types/PoolOperation.sol";

/// @notice Shared setup for every Sworn unit test: a live `PoolManager`, two currencies,
///         a hookless reference pool, and helpers for placing hooks at addresses whose
///         bits actually grant the permissions the fixture needs.
///
/// @dev v4 derives a hook's permissions from its address, so a fixture cannot simply be
///      deployed anywhere. `deployHook` mines the address by construction using
///      `deployCodeTo`, which is how these tests stay honest about permissions.
abstract contract SwornTestBase is Test, Deployers {
    SwornRouter internal sworn;

    /// @dev Permissions every skimming fixture needs: run before the swap, and be allowed
    ///      to return a delta that changes the amounts.
    uint160 internal constant SKIM_FLAGS = uint160(Hooks.BEFORE_SWAP_FLAG | Hooks.BEFORE_SWAP_RETURNS_DELTA_FLAG);

    /// @dev A hook that only reverts or observes needs no delta permission.
    uint160 internal constant OBSERVE_FLAGS = uint160(Hooks.BEFORE_SWAP_FLAG);

    uint256 internal constant DEFAULT_PROBE_GAS = 2_000_000;

    /// @dev Swap size, chosen to be small relative to the pool. v4-core's default test
    ///      liquidity (1e18 over ticks +/-120) holds only ~6e15 per side, so a 1e18 swap
    ///      drains the pool to its price limit and every result becomes an artefact of
    ///      the fixture rather than of the hook.
    uint256 internal constant SWAP_AMOUNT = 1e15;

    /// @dev Liquidity added to every test pool, over a wide range so that a swap of
    ///      SWAP_AMOUNT moves the price negligibly and route comparisons reflect hook
    ///      behaviour rather than depth.
    int256 internal constant DEEP_LIQUIDITY = 1e21;
    int24 internal constant WIDE_LOWER = -60_000;
    int24 internal constant WIDE_UPPER = 60_000;

    PoolKey internal hooklessKey;

    function setUpSworn() internal {
        deployFreshManagerAndRouters();
        (currency0, currency1) = deployMintAndApprove2Currencies();

        sworn = new SwornRouter(manager, ISignatureTransfer(address(0)));

        // The hookless pool every test uses as the honest baseline.
        hooklessKey = initDeepPool(IHooks(address(0)));

        // Fund the router's caller and approve it.
        _approveSworn();
    }

    function _approveSworn() internal {
        deal(Currency.unwrap(currency0), address(this), 1_000_000e18);
        deal(Currency.unwrap(currency1), address(this), 1_000_000e18);
        _approve(currency0);
        _approve(currency1);
    }

    function _approve(
        Currency currency
    ) private {
        (bool ok,) = Currency.unwrap(currency)
            .call(abi.encodeWithSignature("approve(address,uint256)", address(sworn), type(uint256).max));
        require(ok, "approve failed");
    }

    /// @notice Deploy a fixture at an address carrying `flags`, and init a pool on it.
    /// @param name the fixture contract's name, e.g. "GaspriceSniffHook"
    /// @dev Artifacts are referenced by output path, not by `File.sol:Name`. The name
    ///      form does not resolve for these fixtures under this Foundry version, and a
    ///      silent `vm.getCode` miss reads like a test-logic failure rather than a
    ///      lookup failure, so the path form is used deliberately.
    /// @param args abi-encoded constructor arguments
    function deployHookAndPool(
        string memory name,
        bytes memory args,
        uint160 flags,
        uint256 salt
    ) internal returns (address hookAddress, PoolKey memory key) {
        // Any address with the right low bits works; `salt` keeps fixtures distinct.
        // The cast is bounded by construction: `salt` is a small test-supplied counter.
        require(salt < (1 << 128), "salt too large");
        // forge-lint: disable-next-line(unsafe-typecast)
        uint160 saltBits = uint160(salt) << 16;
        hookAddress = address(flags | saltBits);
        deployCodeTo(string.concat("out/ToxicHooks.sol/", name, ".json"), args, hookAddress);
        key = initDeepPool(IHooks(hookAddress));
    }

    /// @notice Initialise a pool at 1:1 and give it liquidity deep enough to price fairly.
    function initDeepPool(
        IHooks hooks
    ) internal returns (PoolKey memory key) {
        (key,) = initPool(currency0, currency1, hooks, 3000, SQRT_PRICE_1_1);
        modifyLiquidityRouter.modifyLiquidity(
            key,
            ModifyLiquidityParams({
                tickLower: WIDE_LOWER, tickUpper: WIDE_UPPER, liquidityDelta: DEEP_LIQUIDITY, salt: 0
            }),
            ""
        );
    }

    /// @notice Same as `deployHookAndPool`, for fixtures in `RecordingHooks.sol`.
    function deployRecordingHookAndPool(
        string memory name,
        bytes memory args,
        uint160 flags,
        uint256 salt
    ) internal returns (address hookAddress, PoolKey memory key) {
        require(salt < (1 << 128), "salt too large");
        // forge-lint: disable-next-line(unsafe-typecast)
        uint160 saltBits = uint160(salt) << 16;
        hookAddress = address(flags | saltBits);
        deployCodeTo(string.concat("out/RecordingHooks.sol/", name, ".json"), args, hookAddress);
        // Clear any recording left by a previous run. The recorder writes to a file so
        // that it survives the probe's revert; files also outlive the test process, so a
        // stale one would be read as this test's observations.
        string memory obs = string.concat("out/sworn-obs-", vm.toString(hookAddress), ".txt");
        if (vm.exists(obs)) vm.removeFile(obs);
        key = initDeepPool(IHooks(hookAddress));
    }

    // -----------------------------------------------------------------------------------
    // route construction
    // -----------------------------------------------------------------------------------

    function singleHop(
        PoolKey memory key,
        bool zeroForOne
    ) internal pure returns (Candidate memory c) {
        c.hops = new Hop[](1);
        c.hops[0] = Hop({key: key, zeroForOne: zeroForOne, hookData: ""});
    }

    function candidates(
        PoolKey memory a,
        PoolKey memory b,
        bool zeroForOne
    ) internal pure returns (Candidate[] memory out) {
        out = new Candidate[](2);
        out[0] = singleHop(a, zeroForOne);
        out[1] = singleHop(b, zeroForOne);
    }

    function defaultParams() internal view returns (SwornParams memory) {
        return SwornParams({
            tokenIn: currency0,
            tokenOut: currency1,
            // forge-lint: disable-next-line(unsafe-typecast)
            amountSpecified: -int256(SWAP_AMOUNT),
            minOut: 0,
            hookMarginBps: 0,
            // forge-lint: disable-next-line(unsafe-typecast)
            probeGas: uint64(DEFAULT_PROBE_GAS),
            maxProbes: 8,
            recipient: address(this),
            deadline: type(uint256).max,
            usePermit2: false,
            permit: ""
        });
    }
}
