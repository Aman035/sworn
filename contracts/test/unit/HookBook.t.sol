// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";

import {HookBook} from "../../src/HookBook.sol";

/// @notice Attestation registry: authorisation, freshness, and the distinction between
///         "measured as clean" and "never measured".
contract HookBookTest is Test {
    HookBook internal book;

    address internal owner = address(0xABCD);
    address internal hook = address(0xBEEF);
    address internal stranger = address(0xDEAD);

    uint256 internal attestorKey = 0xA11CE;
    address internal attestor;

    bytes32 internal constant SNAPSHOT = keccak256("census-base@f96d365");

    function setUp() public {
        attestor = vm.addr(attestorKey);
        book = new HookBook(owner);
        vm.prank(owner);
        book.setAttestor(attestor, true);
    }

    // -----------------------------------------------------------------------------------
    // absence is not innocence
    // -----------------------------------------------------------------------------------

    function test_unscoredHookReadsAsInsufficientData() public view {
        // The whole point of claim 4: a low score must *mean* something, so "never
        // measured" cannot be indistinguishable from "measured and clean".
        assertFalse(book.hasScore(hook));
        assertEq(book.flags(hook), book.FLAG_INSUFFICIENT_DATA());
        (,, bool scored) = book.scoreWithAge(hook);
        assertFalse(scored);
    }

    function test_scoredCleanHookIsDistinguishableFromUnscored() public {
        vm.prank(attestor);
        book.setScore(hook, 0, 0, 1000, SNAPSHOT);

        assertTrue(book.hasScore(hook));
        assertEq(book.score(hook), 0);
        assertEq(book.flags(hook), 0, "a measured-clean hook must not read as INSUFFICIENT_DATA");
    }

    // -----------------------------------------------------------------------------------
    // authorisation
    // -----------------------------------------------------------------------------------

    function test_onlyAttestorCanWrite() public {
        vm.prank(stranger);
        vm.expectRevert(HookBook.NotAttestor.selector);
        book.setScore(hook, 50, 0, 1000, SNAPSHOT);
    }

    function test_onlyOwnerCanManageAttestors() public {
        vm.prank(stranger);
        vm.expectRevert(HookBook.NotOwner.selector);
        book.setAttestor(stranger, true);
    }

    function test_revokedAttestorCannotWrite() public {
        vm.prank(owner);
        book.setAttestor(attestor, false);
        assertEq(book.attestorCount(), 0);

        vm.prank(attestor);
        vm.expectRevert(HookBook.NotAttestor.selector);
        book.setScore(hook, 50, 0, 1000, SNAPSHOT);
    }

    function test_attestorCountTracksTheSet() public {
        assertEq(book.attestorCount(), 1);
        vm.startPrank(owner);
        book.setAttestor(address(0x1111), true);
        assertEq(book.attestorCount(), 2);
        // Re-authorising an existing attestor must not double count.
        book.setAttestor(address(0x1111), true);
        assertEq(book.attestorCount(), 2);
        book.setAttestor(address(0x1111), false);
        assertEq(book.attestorCount(), 1);
        vm.stopPrank();
    }

    // -----------------------------------------------------------------------------------
    // freshness and replay
    // -----------------------------------------------------------------------------------

    function test_staleUpdateIsRejected() public {
        vm.startPrank(attestor);
        book.setScore(hook, 60, 0, 2000, SNAPSHOT);

        // An older measurement can never overwrite a newer one, whether it arrives late
        // or is replayed deliberately.
        vm.expectRevert(abi.encodeWithSelector(HookBook.StaleUpdate.selector, uint64(1999), uint64(2000)));
        book.setScore(hook, 0, 0, 1999, SNAPSHOT);

        vm.expectRevert(abi.encodeWithSelector(HookBook.StaleUpdate.selector, uint64(2000), uint64(2000)));
        book.setScore(hook, 0, 0, 2000, SNAPSHOT);
        vm.stopPrank();

        assertEq(book.score(hook), 60, "stale write changed the score");
    }

    function test_newerUpdateReplacesTheOlder() public {
        vm.startPrank(attestor);
        book.setScore(hook, 60, book.FLAG_DIVERGENT(), 2000, SNAPSHOT);
        book.setScore(hook, 5, 0, 3000, SNAPSHOT);
        vm.stopPrank();

        assertEq(book.score(hook), 5);
        assertEq(book.flags(hook), 0);
        assertEq(book.proof(hook).asOfBlock, 3000);
    }

    function test_scoreAboveMaxIsRejected() public {
        vm.prank(attestor);
        vm.expectRevert(abi.encodeWithSelector(HookBook.ScoreTooHigh.selector, uint8(101)));
        book.setScore(hook, 101, 0, 1000, SNAPSHOT);
    }

    // -----------------------------------------------------------------------------------
    // signatures
    // -----------------------------------------------------------------------------------

    function _sign(
        uint256 key,
        address h,
        uint8 s,
        uint32 f,
        uint64 blockNo
    ) internal view returns (bytes memory) {
        bytes32 typehash = keccak256(
            "Score(address hook,uint8 score,uint32 flags,uint64 asOfBlock,bytes32 snapshotHash,uint256 chainId)"
        );
        bytes32 digest = keccak256(
            abi.encodePacked(
                "\x19\x01",
                book.domainSeparator(),
                keccak256(abi.encode(typehash, h, s, f, blockNo, SNAPSHOT, block.chainid))
            )
        );
        (uint8 v, bytes32 r, bytes32 sig) = vm.sign(key, digest);
        return abi.encodePacked(r, sig, v);
    }

    function test_relayedSignedScoreIsAccepted() public {
        bytes memory sig = _sign(attestorKey, hook, 42, book.FLAG_ENV_SENSITIVE(), 5000);

        // Anyone may relay: the attestor key never needs gas and never touches a hot path.
        vm.prank(stranger);
        book.setScoreWithSig(hook, 42, book.FLAG_ENV_SENSITIVE(), 5000, SNAPSHOT, sig);

        assertEq(book.score(hook), 42);
        assertTrue(book.hasFlag(hook, book.FLAG_ENV_SENSITIVE()));
    }

    function test_signatureFromANonAttestorIsRejected() public {
        bytes memory sig = _sign(0xBADBAD, hook, 0, 0, 5000);
        vm.expectRevert(HookBook.BadSignature.selector);
        book.setScoreWithSig(hook, 0, 0, 5000, SNAPSHOT, sig);
    }

    function test_tamperedSignedScoreIsRejected() public {
        bytes memory sig = _sign(attestorKey, hook, 42, 0, 5000);
        // Signature covers the score, so submitting a different one must not verify.
        vm.expectRevert(HookBook.BadSignature.selector);
        book.setScoreWithSig(hook, 0, 0, 5000, SNAPSHOT, sig);
    }

    function test_replayedSignatureIsRejectedByMonotonicity() public {
        bytes memory sig = _sign(attestorKey, hook, 42, 0, 5000);
        book.setScoreWithSig(hook, 42, 0, 5000, SNAPSHOT, sig);

        // The same signature is still valid cryptographically; monotonicity is what
        // stops it being replayed.
        vm.expectRevert(abi.encodeWithSelector(HookBook.StaleUpdate.selector, uint64(5000), uint64(5000)));
        book.setScoreWithSig(hook, 42, 0, 5000, SNAPSHOT, sig);
    }

    function test_malleableSignatureIsRejected() public {
        bytes memory sig = _sign(attestorKey, hook, 42, 0, 5000);
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := mload(add(sig, 32))
            s := mload(add(sig, 64))
            v := byte(0, mload(add(sig, 96)))
        }
        // Flip to the other valid (r, s, v) for the same message.
        uint256 n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
        bytes32 sHigh = bytes32(n - uint256(s));
        uint8 vFlipped = v == 27 ? 28 : 27;

        vm.expectRevert(HookBook.BadSignature.selector);
        book.setScoreWithSig(hook, 42, 0, 5000, SNAPSHOT, abi.encodePacked(r, sHigh, vFlipped));
    }

    // -----------------------------------------------------------------------------------
    // batch + proof
    // -----------------------------------------------------------------------------------

    function test_batchWrite() public {
        address[] memory hooks = new address[](2);
        uint8[] memory scores = new uint8[](2);
        uint32[] memory flagsList = new uint32[](2);
        hooks[0] = address(0x1);
        hooks[1] = address(0x2);
        scores[0] = 10;
        scores[1] = 90;
        flagsList[0] = 0;
        flagsList[1] = book.FLAG_DIVERGENT() | book.FLAG_INTERMITTENT();

        vm.prank(attestor);
        book.setScores(hooks, scores, flagsList, 7000, SNAPSHOT);

        assertEq(book.score(address(0x1)), 10);
        assertEq(book.score(address(0x2)), 90);
        assertTrue(book.hasFlag(address(0x2), book.FLAG_INTERMITTENT()));
    }

    function test_batchLengthMismatchReverts() public {
        address[] memory hooks = new address[](2);
        uint8[] memory scores = new uint8[](1);
        uint32[] memory flagsList = new uint32[](2);

        vm.prank(attestor);
        vm.expectRevert(HookBook.LengthMismatch.selector);
        book.setScores(hooks, scores, flagsList, 7000, SNAPSHOT);
    }

    function test_proofCarriesTheSnapshotHash() public {
        vm.prank(attestor);
        book.setScore(hook, 33, 0, 9000, SNAPSHOT);

        HookBook.ScoreProof memory p = book.proof(hook);
        // A reader can fetch this snapshot and re-derive the score rather than trust it.
        assertEq(p.snapshotHash, SNAPSHOT);
        assertEq(p.asOfBlock, 9000);
        assertGt(p.updatedAt, 0);
    }

    function test_scoreWithAgeReportsStaleness() public {
        vm.prank(attestor);
        book.setScore(hook, 33, 0, 9000, SNAPSHOT);

        vm.warp(block.timestamp + 3600);
        (uint8 s, uint64 age, bool scored) = book.scoreWithAge(hook);
        assertEq(s, 33);
        assertEq(age, 3600);
        assertTrue(scored);
    }

    function testFuzz_scoreRoundTrips(
        uint8 s,
        uint32 f,
        uint64 blockNo
    ) public {
        s = uint8(bound(s, 0, book.MAX_SCORE()));
        blockNo = uint64(bound(blockNo, 1, type(uint64).max));

        vm.prank(attestor);
        book.setScore(hook, s, f, blockNo, SNAPSHOT);

        assertEq(book.score(hook), s);
        assertEq(book.flags(hook), f);
        assertEq(book.proof(hook).asOfBlock, blockNo);
    }
}
