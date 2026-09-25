// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Vm} from "forge-std/Vm.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {BaseTestHook, SkimmingHook} from "./BaseTestHook.sol";

/// @notice Hooks that record what they observed somewhere a revert cannot reach.
///
/// @dev Why this exists. `SwornRouter`'s probe reverts, and a revert rolls back every
///      state change the hook made — including its own bookkeeping. That is precisely the
///      property being tested, and it also makes the property impossible to observe from
///      on-chain storage: after a swap, a hook's counter shows the execution only.
///
///      Cheatcode side effects are host-side, not EVM state, so they survive the probe's
///      revert. Writing observations to the environment is therefore the only way to
///      compare what the hook saw during the probe with what it saw during execution.
///      Test-only, obviously: no production hook can do this.
abstract contract RecordingHook is SkimmingHook {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    string internal constant OBSERVATIONS = "SWORN_OBSERVATIONS";

    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {
        vm.setEnv(OBSERVATIONS, "");
    }

    function _record(
        string memory value
    ) internal {
        string memory prev = vm.envOr(OBSERVATIONS, string(""));
        vm.setEnv(OBSERVATIONS, string.concat(prev, ",", value));
    }

    /// @notice Every value recorded across probes and executions, in order.
    function observations() external view returns (string[] memory) {
        string memory raw = vm.envOr(OBSERVATIONS, string(""));
        if (bytes(raw).length == 0) return new string[](0);
        string[] memory parts = vm.split(raw, ",");
        // The leading empty element from the first concat is not an observation.
        string[] memory out = new string[](parts.length - 1);
        for (uint256 i = 1; i < parts.length; i++) {
            out[i - 1] = parts[i];
        }
        return out;
    }
}

/// @notice Records `gasleft()` at hook entry, for probe and execution alike.
/// @dev The reason `SwornRouter` passes an explicit, equal stipend to both calls: if the
///      two differ, this hook's two observations differ and the test fails.
contract RecordingGasSniffHook is RecordingHook {
    constructor(
        IPoolManager _pm
    ) RecordingHook(_pm) {}

    function _feeBps(
        address,
        PoolKey calldata,
        IPoolManager.SwapParams calldata
    ) internal override returns (uint256) {
        _record(vm.toString(gasleft()));
        return 0;
    }
}

/// @notice Calls back into the swapping router and records what it got.
/// @dev `SwornRouter` exposes no phase flag, so both observations must be identical.
contract RecordingCallbackSniffHook is RecordingHook {
    constructor(
        IPoolManager _pm
    ) RecordingHook(_pm) {}

    function _feeBps(
        address sender,
        PoolKey calldata,
        IPoolManager.SwapParams calldata
    ) internal override returns (uint256) {
        // Ask the router something a probe-aware implementation might answer differently.
        (bool ok, bytes memory ret) = sender.staticcall(abi.encodeWithSignature("probing()"));
        _record(vm.toString(keccak256(abi.encode(ok, ret))));
        return 0;
    }
}
