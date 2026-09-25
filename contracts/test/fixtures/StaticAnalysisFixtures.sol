// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @notice Fixtures for the static analyser. Deliberately tiny, so a detection is
///         unambiguous: exactly one of these reads the transaction environment.

/// @dev Reads nothing from the environment. Must produce no env-opcode signals.
contract NoEnvReads {
    uint256 public total;

    function bump(
        uint256 amount
    ) external returns (uint256) {
        total += amount;
        return total;
    }

    /// @dev A constant whose bytes happen to contain 0x3a (GASPRICE) and 0x41 (COINBASE).
    ///      A naive `byte in code` scan reports env reads here; a correct one does not.
    function decoy() external pure returns (bytes32) {
        return 0x3a3a3a3a41414141_3a3a3a3a41414141_3a3a3a3a41414141_3a3a3a3a41414141;
    }
}

/// @dev Reads `tx.gasprice`. Must be detected.
contract ReadsGasPrice {
    function fee() external view returns (uint256) {
        return tx.gasprice == 0 ? 0 : 1800;
    }
}

/// @dev Reads several environment values at once.
contract ReadsManyEnv {
    function signals() external view returns (uint256, address, uint256, uint256) {
        return (tx.gasprice, block.coinbase, block.basefee, block.prevrandao);
    }
}

/// @dev `tx.origin` used for access control — a benign-looking pattern that is still a
///      simulation signal, so it must be detected and then judged, not ignored.
contract ReadsOrigin {
    function isDirect() external view returns (bool) {
        return tx.origin == msg.sender;
    }
}
