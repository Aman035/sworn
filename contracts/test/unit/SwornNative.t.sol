// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {ISignatureTransfer} from "permit2/src/interfaces/ISignatureTransfer.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IERC20Minimal} from "v4-core/src/interfaces/external/IERC20Minimal.sol";
import {Currency, CurrencyLibrary} from "v4-core/src/types/Currency.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {ModifyLiquidityParams} from "v4-core/src/types/PoolOperation.sol";
import {Deployers} from "v4-core/test/utils/Deployers.sol";

import {Candidate, Hop, SwornParams, SwornRouter} from "../../src/SwornRouter.sol";

/// @notice Native ETH settlement.
///
/// @dev Native pools use `currency0 == address(0)` and settle with `settle{value:}`
///      rather than a `sync` + `transferFrom` pair. It is a genuinely different code
///      path, and the one where leftover value would sit in the router, so it gets its
///      own fixture rather than a flag on the ERC20 tests.
contract SwornNativeTest is Test, Deployers {
    SwornRouter internal sworn;

    uint256 internal constant SWAP_AMOUNT = 1e15;
    int256 internal constant DEEP_LIQUIDITY = 1e21;

    function setUp() public {
        deployFreshManagerAndRouters();
        (currency0, currency1) = deployMintAndApprove2Currencies();

        sworn = new SwornRouter(manager, ISignatureTransfer(address(0)));

        Currency native = CurrencyLibrary.ADDRESS_ZERO;
        (nativeKey,) = initPool(native, currency1, IHooks(address(0)), 3000, SQRT_PRICE_1_1);

        // 1e21 liquidity over +/-60,000 ticks needs ~950 ETH on the native side.
        deal(address(this), 5_000 ether);
        modifyLiquidityRouter.modifyLiquidity{value: 2_000 ether}(
            nativeKey,
            ModifyLiquidityParams({tickLower: -60_000, tickUpper: 60_000, liquidityDelta: DEEP_LIQUIDITY, salt: 0}),
            ""
        );
    }

    function _params() internal view returns (SwornParams memory) {
        return SwornParams({
            tokenIn: CurrencyLibrary.ADDRESS_ZERO,
            tokenOut: currency1,
            amountSpecified: -int256(SWAP_AMOUNT),
            minOut: 0,
            hookMarginBps: 0,
            probeGas: 2_000_000,
            maxProbes: 4,
            recipient: address(this),
            deadline: type(uint256).max,
            usePermit2: false,
            permit: ""
        });
    }

    function _candidate() internal view returns (Candidate[] memory cands) {
        cands = new Candidate[](1);
        cands[0].hops = new Hop[](1);
        cands[0].hops[0] = Hop({key: nativeKey, zeroForOne: true, hookData: ""});
    }

    function test_nativeIn_swapsAndRefundsTheDust() public {
        uint256 tokenBefore = IERC20Minimal(Currency.unwrap(currency1)).balanceOf(address(this));
        uint256 ethBefore = address(this).balance;

        // Deliberately overpay: the router must return what it did not spend, or value
        // silently accumulates in it.
        uint256 sent = SWAP_AMOUNT * 2;
        uint256 out = sworn.swornSwap{value: sent}(_candidate(), _params());

        assertGt(out, 0, "no output");
        assertEq(
            IERC20Minimal(Currency.unwrap(currency1)).balanceOf(address(this)) - tokenBefore,
            out,
            "delivered != reported"
        );
        assertEq(ethBefore - address(this).balance, SWAP_AMOUNT, "overpayment was not refunded");
        assertEq(address(sworn).balance, 0, "router retained native value");
    }

    function test_nativeIn_revertsWhenValueIsShort() public {
        // Sending less than the swap needs must fail rather than draw on whatever the
        // router happens to hold.
        vm.expectRevert();
        sworn.swornSwap{value: SWAP_AMOUNT / 2}(_candidate(), _params());
        assertEq(address(sworn).balance, 0, "router retained native value after a failure");
    }
}
