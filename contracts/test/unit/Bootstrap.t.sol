// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Sworn} from "../../src/Sworn.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Phase 0 smoke test: proves the Foundry toolchain compiles and runs.
contract BootstrapTest is Test {
    function test_toolchainIsWired() public pure {
        assertEq(Sworn.VERSION, "0.0.0");
    }
}
