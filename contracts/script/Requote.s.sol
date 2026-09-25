// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {console2 as console} from "forge-std/console2.sol";

import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {StateLibrary} from "v4-core/src/libraries/StateLibrary.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {PoolId, PoolIdLibrary} from "v4-core/src/types/PoolId.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {IV4Quoter} from "v4-periphery/src/interfaces/IV4Quoter.sol";
import {V4Quoter} from "v4-periphery/src/lens/V4Quoter.sol";

/// @notice Re-quote settled fills against the state that existed immediately before them.
///
/// @dev This is the measurement `docs/METRICS.md` calls `expected_output`, and it is the
///      only part of the divergence pipeline that cannot be done from logs alone.
///
///      `vm.rollFork(txHash)` puts the fork at the state *after every earlier transaction
///      in the same block* and before the fill itself. That distinction matters: quoting
///      at the end of block N-1 is cheaper but wrong whenever another swap in the same
///      block moved the pool, which on a busy pool is most of them.
///
///      The quoter is deployed on the fork rather than looked up by address, so the quote
///      comes from the pinned v4-periphery in this repo and not from whatever happens to
///      be deployed on that chain.
///
/// Input : a JSON array of fills (see `analysis/lib/requote.py`).
/// Output: a JSON array of results, written to `--sig` target path.
contract RequoteScript is Script {
    using stdJson for string;
    using PoolIdLibrary for PoolKey;

    struct Fill {
        uint256 amountSpecified; // magnitude; direction is `zeroForOne`
        Currency currency0;
        Currency currency1;
        uint24 fee;
        bytes hookData;
        IHooks hooks;
        /// @dev A transaction can contain many Swap events — up to 126 observed on Base,
        ///      and 37.8% of fills live in multi-fill transactions. The log index is
        ///      therefore part of a fill's identity; keying results by txHash alone
        ///      silently matches one quote against another fill's realized amount.
        uint256 logIndex;
        int24 tickSpacing;
        bytes32 txHash;
        bool zeroForOne;
    }

    /// @notice Re-quote every fill in `inputPath`, writing results to `outputPath`.
    function run(
        string memory inputPath,
        string memory outputPath,
        address poolManager
    ) external {
        string memory raw = vm.readFile(inputPath);
        uint256 count = raw.readUint(".count");

        string memory out = "[";
        for (uint256 i = 0; i < count; i++) {
            string memory base = string.concat(".fills[", vm.toString(i), "]");
            Fill memory f = _readFill(raw, base);

            (bool ok, uint256 expected, string memory err, uint256 quotedAt, uint160 sqrtPrice, bytes32 poolId) =
                _quoteAt(f, IPoolManager(poolManager));

            out = string.concat(
                out,
                i == 0 ? "" : ",",
                '{"txHash":"',
                vm.toString(f.txHash),
                '","logIndex":',
                vm.toString(f.logIndex),
                ',"ok":',
                ok ? "true" : "false",
                ',"expected":"',
                vm.toString(expected),
                '","quotedAtBlock":',
                vm.toString(quotedAt),
                ',"sqrtPriceX96":"',
                vm.toString(sqrtPrice),
                '","poolId":"',
                vm.toString(poolId),
                '","parsedAmount":"',
                vm.toString(f.amountSpecified),
                '","error":"',
                err,
                '"}'
            );
        }
        out = string.concat(out, "]");
        vm.writeFile(outputPath, out);
        console.log("requoted", count, "fills ->", outputPath);
    }

    function _readFill(
        string memory raw,
        string memory base
    ) private pure returns (Fill memory f) {
        f.txHash = raw.readBytes32(string.concat(base, ".txHash"));
        f.currency0 = Currency.wrap(raw.readAddress(string.concat(base, ".currency0")));
        f.currency1 = Currency.wrap(raw.readAddress(string.concat(base, ".currency1")));
        f.fee = uint24(raw.readUint(string.concat(base, ".fee")));
        f.tickSpacing = int24(raw.readInt(string.concat(base, ".tickSpacing")));
        f.hooks = IHooks(raw.readAddress(string.concat(base, ".hooks")));
        f.zeroForOne = raw.readBool(string.concat(base, ".zeroForOne"));
        f.amountSpecified = raw.readUint(string.concat(base, ".amountSpecified"));
        f.hookData = raw.readBytes(string.concat(base, ".hookData"));
        f.logIndex = raw.readUint(string.concat(base, ".logIndex"));
    }

    /// @dev Rolls to the fill's own transaction and quotes the identical swap there.
    ///      Also reports the block actually quoted at and the pool's liquidity there:
    ///      without those, a surprising quote is unfalsifiable — there is no way to tell
    ///      a hook taking value from a fork that never rolled or a pool that was empty.
    function _quoteAt(
        Fill memory f,
        IPoolManager poolManager
    )
        private
        returns (bool ok, uint256 expected, string memory err, uint256 quotedAt, uint160 sqrtPrice, bytes32 poolId)
    {
        try vm.rollFork(f.txHash) {
            quotedAt = block.number;
            // Deploy after rolling: the fork's state is replaced by the roll.
            V4Quoter quoter = new V4Quoter(poolManager);

            PoolKey memory key = PoolKey({
                currency0: f.currency0, currency1: f.currency1, fee: f.fee, tickSpacing: f.tickSpacing, hooks: f.hooks
            });
            poolId = PoolId.unwrap(key.toId());

            try quoter.quoteExactInputSingle(
                IV4Quoter.QuoteExactSingleParams({
                    poolKey: key,
                    zeroForOne: f.zeroForOne,
                    exactAmount: uint128(f.amountSpecified),
                    hookData: f.hookData
                })
            ) returns (
                uint256 amountOut, uint256
            ) {
                (sqrtPrice,,,) = StateLibrary.getSlot0(poolManager, key.toId());
                return (true, amountOut, "", quotedAt, sqrtPrice, poolId);
            } catch Error(string memory reason) {
                return (false, 0, reason, quotedAt, 0, poolId);
            } catch {
                // A hook that reverts for the quoter is itself a finding, not an error.
                return (false, 0, "quote reverted", quotedAt, 0, poolId);
            }
        } catch {
            return (false, 0, "rollFork failed", 0, 0, bytes32(0));
        }
    }
}
