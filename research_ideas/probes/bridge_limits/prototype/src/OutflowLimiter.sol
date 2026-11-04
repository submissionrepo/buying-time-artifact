// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20Min {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// Wrapped asset whose supply this contract controls on the destination chain (mint side).
interface IMintable {
    function mint(address to, uint256 amount) external;
    function burn(address from, uint256 amount) external;
}

/// Optional weight adapter (stub). It is never read on the request or execution path, and it
/// can only raise a weight, which tightens the limit.
interface IWeightSource {
    function weightOf(address asset) external view returns (uint256);
}

/// @title OutflowLimiter
/// @notice Release point of a bridge: escrow withdrawals and mints of wrapped assets pass through
/// here. Every release is queued for at least `hold` seconds (H) and then executed, in request
/// order, against one token bucket of capacity `capacity` (B) refilled at `refillRate` (R) per
/// second. All assets share the bucket through fixed weights in a common unit (for example USD
/// with 18 decimals). Accounting is gross: inflows never refill the bucket. A pauser that is
/// separate from the bridge and the admin can stop execution and cancel queued requests.
contract OutflowLimiter {
    enum Status {
        None,
        Queued,
        Executed,
        Cancelled
    }

    struct Request {
        address asset;
        uint64 readyAt; // request time + hold
        Status status;
        address to;
        uint128 amount; // asset base units
        uint128 value; // common units, rounded up
    }

    uint256 private constant WAD = 1e18;

    address public immutable bridge; // verifier or messaging contract; the only party that queues
    address public immutable admin; // lists assets; cannot pause, cancel, or change B, R, H
    IWeightSource public immutable weightSource; // optional, address(0) if unused
    uint128 public immutable capacity; // B, common units
    uint128 public immutable refillRate; // R, common units per second
    uint64 public immutable hold; // H, seconds

    address public pauser;

    // Bucket state and the pause flag share one storage slot.
    uint128 public tokens;
    uint64 public lastRefill;
    bool public paused;

    // Queue pointers share one storage slot.
    uint64 public head; // lowest id that may still be queued
    uint64 public nextId; // id of the next request

    mapping(address => uint256) public weight; // common units per base unit, scaled by 1e18; 0 = not listed
    mapping(address => bool) public minted; // true: released by minting; false: paid from escrow
    mapping(uint256 => Request) public requests;

    event AssetListed(address indexed asset, uint256 weight, bool minted);
    event WeightRaised(address indexed asset, uint256 weight);
    event Deposited(address indexed asset, address indexed from, uint256 amount, bytes32 recipient);
    event Queued(
        uint256 indexed id, address indexed asset, address indexed to, uint256 amount, uint256 value, uint64 readyAt
    );
    event Executed(uint256 indexed id, uint256 value, uint256 tokensLeft);
    event Cancelled(uint256 indexed id);
    event Paused(address indexed by);
    event Unpaused(address indexed by);
    event PauserTransferred(address indexed from, address indexed to);

    error NotBridge();
    error NotAdmin();
    error NotPauser();
    error BadConfig();
    error BadAsset();
    error BadRequest();
    error AboveCapacity();
    error IsPaused();
    error QueueEmpty();
    error NotReady();
    error OverLimit();
    error NotQueued();
    error TokenCallFailed();

    modifier onlyPauser() {
        if (msg.sender != pauser) revert NotPauser();
        _;
    }

    constructor(
        address bridge_,
        address admin_,
        address pauser_,
        IWeightSource weightSource_,
        uint128 capacity_,
        uint128 refillRate_,
        uint64 hold_
    ) {
        if (bridge_ == address(0) || admin_ == address(0) || capacity_ == 0) revert BadConfig();
        if (pauser_ == address(0) || pauser_ == bridge_ || pauser_ == admin_) revert BadConfig();
        bridge = bridge_;
        admin = admin_;
        pauser = pauser_;
        weightSource = weightSource_;
        capacity = capacity_;
        refillRate = refillRate_;
        hold = hold_;
        tokens = capacity_; // the bucket starts full
        lastRefill = uint64(block.timestamp);
    }

    // ------------------------------------------------------------------ bridge side

    /// Queue a release. The bridge calls this after it has checked the cross-chain message.
    function requestRelease(address asset, address to, uint256 amount) external returns (uint256 id) {
        if (msg.sender != bridge) revert NotBridge();
        uint256 w = weight[asset];
        if (w == 0) revert BadAsset();
        if (amount == 0 || amount > type(uint128).max || to == address(0)) revert BadRequest();
        uint256 value = (amount * w + WAD - 1) / WAD; // rounded up: no release is under-metered
        if (value > capacity) revert AboveCapacity(); // could never fit and would block the queue
        id = nextId++;
        uint64 readyAt = uint64(block.timestamp) + hold;
        requests[id] = Request(asset, readyAt, Status.Queued, to, uint128(amount), uint128(value));
        emit Queued(id, asset, to, amount, value, readyAt);
    }

    /// Lock an escrowed asset or burn a wrapped one. The bucket is not refilled: an inflow does
    /// not raise how much may leave.
    function deposit(address asset, uint256 amount, bytes32 recipient) external {
        if (weight[asset] == 0) revert BadAsset();
        if (amount == 0) revert BadRequest();
        emit Deposited(asset, msg.sender, amount, recipient);
        if (minted[asset]) _call(asset, abi.encodeCall(IMintable.burn, (msg.sender, amount)));
        else _call(asset, abi.encodeCall(IERC20Min.transferFrom, (msg.sender, address(this), amount)));
    }

    // ------------------------------------------------------------------ release

    /// Execute the oldest queued request once its hold has passed and the bucket holds its value.
    /// Anyone may call. Later requests wait behind it (FIFO by id); cancelled ones are skipped.
    function executeNext() external returns (uint256 id) {
        if (paused) revert IsPaused();
        uint256 end = nextId;
        id = head;
        while (id < end && requests[id].status == Status.Cancelled) id++;
        if (id == end) revert QueueEmpty();
        Request storage r = requests[id];
        if (block.timestamp < r.readyAt) revert NotReady();
        uint256 value = r.value;
        uint256 avail = available();
        if (value > avail) revert OverLimit();
        tokens = uint128(avail - value);
        lastRefill = uint64(block.timestamp);
        r.status = Status.Executed;
        head = uint64(id + 1);
        emit Executed(id, value, avail - value);
        if (minted[r.asset]) _call(r.asset, abi.encodeCall(IMintable.mint, (r.to, r.amount)));
        else _call(r.asset, abi.encodeCall(IERC20Min.transfer, (r.to, r.amount)));
    }

    /// Tokens in the bucket now: stored tokens plus R per elapsed second, capped at B.
    function available() public view returns (uint256) {
        uint256 t = uint256(tokens) + uint256(refillRate) * (block.timestamp - lastRefill);
        return t < capacity ? t : capacity;
    }

    // ------------------------------------------------------------------ pauser

    function pause() external onlyPauser {
        paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external onlyPauser {
        paused = false;
        emit Unpaused(msg.sender);
    }

    /// Cancel a queued request. Nothing is paid out: escrowed funds never left and nothing was minted.
    function cancel(uint256 id) external onlyPauser {
        Request storage r = requests[id];
        if (r.status != Status.Queued) revert NotQueued();
        r.status = Status.Cancelled;
        emit Cancelled(id);
    }

    /// Only the pauser can hand the role on, and never to the bridge or the admin.
    function transferPauser(address next) external onlyPauser {
        if (next == address(0) || next == bridge || next == admin) revert BadConfig();
        emit PauserTransferred(pauser, next);
        pauser = next;
    }

    // ------------------------------------------------------------------ admin

    /// List an asset once, with a fixed weight.
    function listAsset(address asset, uint256 weight_, bool minted_) external {
        if (msg.sender != admin) revert NotAdmin();
        if (weight_ == 0 || weight[asset] != 0 || asset.code.length == 0) revert BadAsset();
        weight[asset] = weight_;
        minted[asset] = minted_;
        emit AssetListed(asset, weight_, minted_);
    }

    /// Optional adapter: anyone may pull a higher weight from `weightSource`. A weight never
    /// falls, so the source can slow releases of an asset but cannot loosen the limit.
    function raiseWeight(address asset) external {
        uint256 w = weightSource.weightOf(asset);
        if (weight[asset] == 0 || w <= weight[asset]) revert BadAsset();
        weight[asset] = w;
        emit WeightRaised(asset, w);
    }

    // ------------------------------------------------------------------ internal

    /// Token call that accepts both bool-returning and non-returning tokens.
    function _call(address token, bytes memory data) private {
        (bool ok, bytes memory ret) = token.call(data);
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TokenCallFailed();
    }
}
