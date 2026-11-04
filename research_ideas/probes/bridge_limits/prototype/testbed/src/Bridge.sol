// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// Testbed contracts around the prototype limiters. The limiters themselves are compiled unchanged
// from ../src (see Imports.sol).

interface ITokenIn {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

interface ILimiterRequest {
    function requestRelease(address asset, address to, uint256 amount) external returns (uint256 id);
}

interface ILimiterExecute {
    function executeNext() external returns (uint256 id);
}

/// Source chain: locks the test token and records each deposit under an id chosen by the
/// depositor (the replayed row), so that a deposit dropped by a reorganization and sent again keeps
/// its id.
contract SourceDeposit {
    struct Dep {
        uint128 amount;
        address recipient;
        uint64 blockNumber;
    }

    ITokenIn public immutable token;
    mapping(bytes32 => Dep) public deposits;

    event Deposited(bytes32 indexed id, address indexed from, address indexed recipient, uint256 amount);

    error UsedId();
    error BadAmount();

    constructor(ITokenIn token_) {
        token = token_;
    }

    function deposit(bytes32 id, uint256 amount, address recipient) external {
        if (amount == 0 || amount > type(uint128).max) revert BadAmount();
        if (deposits[id].amount != 0) revert UsedId();
        deposits[id] = Dep(uint128(amount), recipient, uint64(block.number));
        emit Deposited(id, msg.sender, recipient, amount);
        require(token.transferFrom(msg.sender, address(this), amount), "transfer");
    }

    /// The failure injected by the forged-deposit episodes: a deposit path whose check failed, so it
    /// records and announces a deposit without moving value (an EVENT failure). Legitimate traffic
    /// never calls it.
    function depositUnchecked(bytes32 id, uint256 amount, address recipient) external {
        if (amount == 0 || amount > type(uint128).max) revert BadAmount();
        if (deposits[id].amount != 0) revert UsedId();
        deposits[id] = Dep(uint128(amount), recipient, uint64(block.number));
        emit Deposited(id, msg.sender, recipient, amount);
    }
}

/// Destination chain: the bridge's receiving contract. Only the bridge's two relayer keys may call
/// it; it refuses an id it has already relayed and passes the release to the limiter, whose only
/// requester it is. The event carries the source deposit id next to the limiter's request id, which
/// is what an independent monitor matches against the source chain. (Two keys let the honest relayer
/// and a party holding the other key send at the same time without sharing a nonce.)
contract Receiver {
    address public immutable relayer;
    address public immutable relayer2;
    address public immutable deployer;
    address public immutable asset;
    ILimiterRequest public limiter;

    mapping(bytes32 => bool) public processed;

    event Relayed(bytes32 indexed id, uint256 indexed requestId, address indexed to, uint256 amount);

    error NotRelayer();
    error Processed();
    error AlreadySet();

    constructor(address relayer_, address relayer2_, address asset_) {
        relayer = relayer_;
        relayer2 = relayer2_;
        asset = asset_;
        deployer = msg.sender;
    }

    /// The limiter takes this contract's address as its bridge, so it is set once after both exist.
    function setLimiter(ILimiterRequest limiter_) external {
        if (msg.sender != deployer || address(limiter) != address(0)) revert AlreadySet();
        limiter = limiter_;
    }

    function relay(bytes32 id, address to, uint256 amount) external returns (uint256 requestId) {
        if (msg.sender != relayer && msg.sender != relayer2) revert NotRelayer();
        if (processed[id]) revert Processed();
        processed[id] = true;
        requestId = limiter.requestRelease(asset, to, amount);
        emit Relayed(id, requestId, to, amount);
    }
}

/// Executes queued requests until one cannot be executed (not ready, over the limit, paused or
/// queue empty). Anyone may call executeNext on the limiter; this only saves transactions.
contract Executor {
    function drain(ILimiterExecute limiter, uint256 maxN) external returns (uint256 n) {
        for (; n < maxN; n++) {
            try limiter.executeNext() returns (uint256) {}
            catch {
                break;
            }
        }
    }
}
