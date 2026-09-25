// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Script} from "forge-std/Script.sol";
import {console2 as console} from "forge-std/console2.sol";

import {HookBook} from "../src/HookBook.sol";

/// @notice Deploy `HookBook` and authorise the attestor in one transaction set.
///
/// @dev The deployer becomes owner and the attestor is authorised immediately, because a
///      registry with no attestor cannot be written and a two-step setup invites the gap
///      being forgotten. Ownership can be moved afterwards; the attestor set is designed
///      to grow to N-of-M without a migration.
///
///   forge script script/DeployHookBook.s.sol:DeployHookBook \
///     --rpc-url "$BASE_SEPOLIA_RPC" --broadcast
contract DeployHookBook is Script {
    function run() external {
        uint256 pk = vm.envUint("ATTESTOR_PK");
        address attestor = vm.addr(pk);

        // The deploying key is also the first attestor here. On mainnet these should be
        // different keys: the owner can change the attestor set, the attestor cannot.
        address owner = vm.envOr("HOOKBOOK_OWNER", attestor);

        vm.startBroadcast(pk);
        HookBook book = new HookBook(owner);
        book.setAttestor(attestor, true);
        vm.stopBroadcast();

        console.log("HookBook deployed at:", address(book));
        console.log("owner:              ", owner);
        console.log("attestor authorised:", attestor);
        console.log("chain id:           ", block.chainid);
    }
}
