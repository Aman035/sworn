// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Vm} from "forge-std/Vm.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";

import {BaseTestHook, SkimmingHook} from "./BaseTestHook.sol";
import {SwapParams} from "v4-core/src/types/PoolOperation.sol";

/// @notice Hooks that record what they observed somewhere a revert cannot reach.
///
/// @dev Why this exists. `SwornRouter`'s probe reverts, and a revert rolls back every
///      state change the hook made, including its own bookkeeping. That is precisely the
///      property being tested, and it also makes the property impossible to observe from
///      on-chain storage: after a swap, a hook's counter shows the execution only.
///
///      Cheatcode side effects are host-side, not EVM state, so they survive the probe's
///      revert. Writing observations to the environment is therefore the only way to
///      compare what the hook saw during the probe with what it saw during execution.
///      Test-only, obviously: no production hook can do this.
abstract contract RecordingHook is SkimmingHook {
    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    /// @dev One file per hook instance.
    ///
    ///      An earlier version of this used `vm.setEnv`, which is wrong: forge runs test
    ///      functions in parallel and the env cheatcode mutates process environment,
    ///      which is not thread-safe. Two tests recording concurrently lost each other's
    ///      writes and the suite failed a different subset on every run: a flaky test,
    ///      which is worse than a failing one. Per-path file I/O has no such race.
    function _path() internal view returns (string memory) {
        return string.concat("out/sworn-obs-", vm.toString(address(this)), ".txt");
    }

    constructor(
        IPoolManager _pm
    ) SkimmingHook(_pm) {}

    function _record(
        string memory value
    ) internal {
        vm.writeLine(_path(), value);
    }

    /// @notice Every value recorded across probes and executions, in order.
    function observations() external view returns (string[] memory) {
        string memory raw;
        try vm.readFile(_path()) returns (string memory contents) {
            raw = contents;
        } catch {
            return new string[](0);
        }
        if (bytes(raw).length == 0) return new string[](0);

        string[] memory parts = vm.split(raw, "\n");
        // `writeLine` leaves a trailing newline, so the last element is empty.
        uint256 count = parts.length;
        while (count > 0 && bytes(parts[count - 1]).length == 0) {
            count--;
        }
        string[] memory out = new string[](count);
        for (uint256 i = 0; i < count; i++) {
            out[i] = parts[i];
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
        SwapParams calldata
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
        SwapParams calldata
    ) internal override returns (uint256) {
        // Ask the router something a probe-aware implementation might answer differently.
        (bool ok, bytes memory ret) = sender.staticcall(abi.encodeWithSignature("probing()"));
        _record(string.concat(ok ? "ok:" : "revert:", vm.toString(ret)));
        return 0;
    }
}

/// @notice A hook that *actually* defeats the probe, to prove the safety net fires.
///
/// @dev Every other fixture in this repo loses to Sworn, because the EVM gives a hook no
///      way to distinguish a probe from an execution. This one cheats: it keeps its
///      invocation count host-side, where the probe's revert cannot reach it, so it can
///      quote free and then charge.
///
///      No deployed hook can do this: it requires cheatcodes. That is the point. The
///      `Divergence` assertion exists for the case where the reasoning in
///      docs/THREAT_MODEL.md is *wrong*, and this fixture manufactures exactly that case
///      so the last line of defence is tested rather than merely argued for.
contract CheatingDivergentHook is RecordingHook {
    constructor(
        IPoolManager _pm
    ) RecordingHook(_pm) {}

    function _feeBps(
        address,
        PoolKey calldata,
        SwapParams calldata
    ) internal override returns (uint256) {
        uint256 seen = this.observations().length;
        _record(vm.toString(seen + 1));
        // First call (the probe) is free; every later call charges.
        return seen == 0 ? 0 : 1_800;
    }
}
