// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {stdJson} from "forge-std/StdJson.sol";
import {console2 as console} from "forge-std/console2.sol";

import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
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

    struct Fill {
        uint256 amountSpecified; // magnitude; direction is `zeroForOne`
        Currency currency0;
        Currency currency1;
        uint24 fee;
        bytes hookData;
        IHooks hooks;
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
        uint256 count = abi.decode(raw.parseRaw(".count"), (uint256));

        string memory out = "[";
        for (uint256 i = 0; i < count; i++) {
            string memory base = string.concat(".fills[", vm.toString(i), "]");
            Fill memory f = _readFill(raw, base);

            (bool ok, uint256 expected, string memory err) = _quoteAt(f, IPoolManager(poolManager));

            out = string.concat(
                out,
                i == 0 ? "" : ",",
                '{"txHash":"',
                vm.toString(f.txHash),
                '","ok":',
                ok ? "true" : "false",
                ',"expected":"',
                vm.toString(expected),
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
        f.txHash = abi.decode(raw.parseRaw(string.concat(base, ".txHash")), (bytes32));
        f.currency0 = Currency.wrap(abi.decode(raw.parseRaw(string.concat(base, ".currency0")), (address)));
        f.currency1 = Currency.wrap(abi.decode(raw.parseRaw(string.concat(base, ".currency1")), (address)));
        f.fee = uint24(abi.decode(raw.parseRaw(string.concat(base, ".fee")), (uint256)));
        f.tickSpacing = int24(abi.decode(raw.parseRaw(string.concat(base, ".tickSpacing")), (int256)));
        f.hooks = IHooks(abi.decode(raw.parseRaw(string.concat(base, ".hooks")), (address)));
        f.zeroForOne = abi.decode(raw.parseRaw(string.concat(base, ".zeroForOne")), (bool));
        f.amountSpecified = abi.decode(raw.parseRaw(string.concat(base, ".amountSpecified")), (uint256));
        f.hookData = abi.decode(raw.parseRaw(string.concat(base, ".hookData")), (bytes));
    }

    /// @dev Rolls to the fill's own transaction and quotes the identical swap there.
    function _quoteAt(
        Fill memory f,
        IPoolManager poolManager
    ) private returns (bool ok, uint256 expected, string memory err) {
        try vm.rollFork(f.txHash) {
            // Deploy after rolling: the fork's state is replaced by the roll.
            V4Quoter quoter = new V4Quoter(poolManager);

            PoolKey memory key = PoolKey({
                currency0: f.currency0, currency1: f.currency1, fee: f.fee, tickSpacing: f.tickSpacing, hooks: f.hooks
            });

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
                return (true, amountOut, "");
            } catch Error(string memory reason) {
                return (false, 0, reason);
            } catch {
                // A hook that reverts for the quoter is itself a finding, not an error.
                return (false, 0, "quote reverted");
            }
        } catch {
            return (false, 0, "rollFork failed");
        }
    }
}
