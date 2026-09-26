// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// @title HookBook
/// @notice On-chain, per-hook divergence scores and behavioural flags.
///
/// @dev Why this exists. `SwornRouter` makes quote spoofing impossible for anyone routing
///      through it, but it says nothing to the rest of the ecosystem. Today the only
///      signal about a hook is whether somebody curated it into a list. Provenance, not
///      behaviour. An honest hook builder has no way to *prove* honesty, so routers that
///      get burned respond by dropping hooked pools wholesale, which punishes exactly the
///      builders the ecosystem needs.
///
///      HookBook publishes measured behaviour instead: a 0-100 score, a flags word, the
///      block the measurement was taken at, and the sha256 of the dataset behind it, so
///      any reader can re-derive the number rather than trust it.
///
/// @dev Three properties the design deliberately keeps:
///
///      * **Scores are advisory.** Nothing here is consulted by `SwornRouter`'s guarantee.
///        A stale, wrong or absent score cannot cause a bad fill; at most it costs gas by
///        skipping a probe. The execution path never trusts this contract.
///      * **Absence is not innocence.** An unscored hook reads as `INSUFFICIENT_DATA`, not
///        as score 0. A low score has to *mean* something for certification to work.
///      * **Updates are monotonic in `asOfBlock`.** That is replay protection and
///        staleness protection in one: an old signed score can never overwrite a newer one.
contract HookBook {
    // ---------------------------------------------------------------------------------
    // flags. Bit positions are frozen; see `flags:` in analysis/config.yaml
    // ---------------------------------------------------------------------------------

    uint32 public constant FLAG_DIVERGENT = 1 << 0;
    uint32 public constant FLAG_ENV_SENSITIVE = 1 << 1;
    uint32 public constant FLAG_INTERMITTENT = 1 << 2;
    uint32 public constant FLAG_UPGRADEABLE = 1 << 3;
    uint32 public constant FLAG_OWNER_SWITCHED = 1 << 4;
    uint32 public constant FLAG_REVERT_GATED = 1 << 5;
    uint32 public constant FLAG_DYNAMIC_FEE = 1 << 6;
    uint32 public constant FLAG_RETURNS_DELTA = 1 << 7;
    uint32 public constant FLAG_ALLOWLISTED = 1 << 8;
    uint32 public constant FLAG_VERIFIED = 1 << 9;
    uint32 public constant FLAG_INSUFFICIENT_DATA = 1 << 10;

    uint8 public constant MAX_SCORE = 100;

    struct ScoreProof {
        uint8 score;
        uint32 flags;
        /// @dev The chain block the measurement describes.
        uint64 asOfBlock;
        /// @dev When this record was written, for staleness checks.
        uint64 updatedAt;
        /// @dev sha256 of the snapshot the score was computed from, so a reader can
        ///      fetch the dataset and re-derive the number instead of trusting it.
        bytes32 snapshotHash;
    }

    mapping(address hook => ScoreProof) private _proofs;

    mapping(address attestor => bool) public isAttestor;
    address public owner;
    uint256 public attestorCount;

    // EIP-712, so a score can be signed off-chain and relayed by anyone.
    bytes32 private constant SCORE_TYPEHASH =
        keccak256("Score(address hook,uint8 score,uint32 flags,uint64 asOfBlock,bytes32 snapshotHash,uint256 chainId)");
    bytes32 private immutable _domainSeparator;

    event ScoreSet(
        address indexed hook,
        uint8 score,
        uint32 flags,
        uint64 asOfBlock,
        bytes32 snapshotHash,
        address indexed attestor
    );
    event AttestorSet(address indexed attestor, bool authorized);
    event OwnerSet(address indexed owner);

    error NotOwner();
    error NotAttestor();
    error ScoreTooHigh(uint8 score);
    error StaleUpdate(uint64 asOfBlock, uint64 storedAsOfBlock);
    error BadSignature();
    error LengthMismatch();
    error ZeroAddress();

    constructor(
        address _owner
    ) {
        if (_owner == address(0)) revert ZeroAddress();
        owner = _owner;
        emit OwnerSet(_owner);

        _domainSeparator = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("HookBook"),
                keccak256("1"),
                block.chainid,
                address(this)
            )
        );
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    // ---------------------------------------------------------------------------------
    // reads
    // ---------------------------------------------------------------------------------

    /// @notice The hook's divergence score, 0 (clean) to 100 (avoid).
    /// @dev An unscored hook returns 0. Check `hasScore` or the `INSUFFICIENT_DATA`
    ///      flag before reading this as a clean bill of health.
    function score(
        address hook
    ) external view returns (uint8) {
        return _proofs[hook].score;
    }

    function flags(
        address hook
    ) external view returns (uint32) {
        ScoreProof memory p = _proofs[hook];
        return p.updatedAt == 0 ? FLAG_INSUFFICIENT_DATA : p.flags;
    }

    /// @notice Whether this hook has ever been scored.
    function hasScore(
        address hook
    ) public view returns (bool) {
        return _proofs[hook].updatedAt != 0;
    }

    /// @notice The full record, including the snapshot hash to re-derive the score from.
    function proof(
        address hook
    ) external view returns (ScoreProof memory) {
        return _proofs[hook];
    }

    /// @notice Score plus how old the measurement is, for callers that gate on freshness.
    function scoreWithAge(
        address hook
    ) external view returns (uint8 s, uint64 ageSeconds, bool scored) {
        ScoreProof memory p = _proofs[hook];
        scored = p.updatedAt != 0;
        s = p.score;
        ageSeconds = scored ? uint64(block.timestamp) - p.updatedAt : type(uint64).max;
    }

    function hasFlag(
        address hook,
        uint32 flag
    ) external view returns (bool) {
        return (_proofs[hook].flags & flag) != 0;
    }

    function domainSeparator() external view returns (bytes32) {
        return _domainSeparator;
    }

    // ---------------------------------------------------------------------------------
    // writes
    // ---------------------------------------------------------------------------------

    function setScore(
        address hook,
        uint8 s,
        uint32 f,
        uint64 asOfBlock,
        bytes32 snapshotHash
    ) external {
        if (!isAttestor[msg.sender]) revert NotAttestor();
        _write(hook, s, f, asOfBlock, snapshotHash, msg.sender);
    }

    function setScores(
        address[] calldata hooks,
        uint8[] calldata scores,
        uint32[] calldata flagsList,
        uint64 asOfBlock,
        bytes32 snapshotHash
    ) external {
        if (!isAttestor[msg.sender]) revert NotAttestor();
        if (hooks.length != scores.length || hooks.length != flagsList.length) revert LengthMismatch();
        for (uint256 i = 0; i < hooks.length; i++) {
            _write(hooks[i], scores[i], flagsList[i], asOfBlock, snapshotHash, msg.sender);
        }
    }

    /// @notice Submit a score signed by an attestor. Anyone may relay it.
    /// @dev Lets the attestor key stay off any hot path and hold no gas: a keeper, a
    ///      dashboard or the hook's own developer can pay for the write.
    function setScoreWithSig(
        address hook,
        uint8 s,
        uint32 f,
        uint64 asOfBlock,
        bytes32 snapshotHash,
        bytes calldata signature
    ) external {
        bytes32 digest = keccak256(
            abi.encodePacked(
                "\x19\x01",
                _domainSeparator,
                keccak256(abi.encode(SCORE_TYPEHASH, hook, s, f, asOfBlock, snapshotHash, block.chainid))
            )
        );
        address signer = _recover(digest, signature);
        if (signer == address(0) || !isAttestor[signer]) revert BadSignature();
        _write(hook, s, f, asOfBlock, snapshotHash, signer);
    }

    function _write(
        address hook,
        uint8 s,
        uint32 f,
        uint64 asOfBlock,
        bytes32 snapshotHash,
        address attestor
    ) private {
        if (s > MAX_SCORE) revert ScoreTooHigh(s);

        ScoreProof storage stored = _proofs[hook];
        // Monotonic in `asOfBlock`: replay protection and staleness protection at once.
        // A re-broadcast of an old signature is rejected for the same reason a late
        // arrival is: it describes a world that has already been superseded.
        if (stored.updatedAt != 0 && asOfBlock <= stored.asOfBlock) {
            revert StaleUpdate(asOfBlock, stored.asOfBlock);
        }

        stored.score = s;
        stored.flags = f;
        stored.asOfBlock = asOfBlock;
        stored.updatedAt = uint64(block.timestamp);
        stored.snapshotHash = snapshotHash;

        emit ScoreSet(hook, s, f, asOfBlock, snapshotHash, attestor);
    }

    // ---------------------------------------------------------------------------------
    // attestor set
    // ---------------------------------------------------------------------------------

    /// @dev Starts as a single key and is structured for N-of-M later: the set is already
    ///      a set, and signatures are already EIP-712, so a threshold is an additive
    ///      change rather than a migration.
    function setAttestor(
        address attestor,
        bool authorized
    ) external onlyOwner {
        if (attestor == address(0)) revert ZeroAddress();
        if (isAttestor[attestor] == authorized) return;
        isAttestor[attestor] = authorized;
        attestorCount = authorized ? attestorCount + 1 : attestorCount - 1;
        emit AttestorSet(attestor, authorized);
    }

    function transferOwnership(
        address newOwner
    ) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        owner = newOwner;
        emit OwnerSet(newOwner);
    }

    function _recover(
        bytes32 digest,
        bytes calldata signature
    ) private pure returns (address) {
        if (signature.length != 65) return address(0);
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly ("memory-safe") {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        // Reject the malleable upper half of the curve order.
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            return address(0);
        }
        if (v != 27 && v != 28) return address(0);
        return ecrecover(digest, v, r, s);
    }
}
