// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20Min, IMintable} from "./OutflowLimiter.sol";

/// @title TunedLimiter
/// @notice The rule of OutflowLimiter with the operator controls the paper recommends:
///  - up to four token buckets in series, which follow the least concave majorant of the traffic at
///    several response times (Observation 7.5); a release must fit every bucket;
///  - an optional bucket per asset, in the asset's own units (Corollary 4.2, Proposition 7.6);
///  - parameters a tuner can tighten at once but loosen only `loosenDelay` seconds after proposing,
///    while the pauser can cancel a pending loosening (Proposition 4.4).
/// Every release is queued for at least `hold` seconds and executed in request order; a pauser
/// separate from the bridge, the admin and the tuner can stop execution and cancel requests.
contract TunedLimiter {
    enum Status {
        None,
        Queued,
        Executed,
        Cancelled
    }

    struct Request {
        address asset;
        uint64 readyAt;
        Status status;
        address to;
        uint128 amount; // asset base units
        uint128 value; // common units, rounded up
    }

    /// A token bucket: capacity and refill per second.
    struct Params {
        uint128 capacity;
        uint128 refill;
    }

    /// The per-asset bucket, in asset base units. capacity 0 means no per-asset limit.
    struct AssetBucket {
        uint128 capacity;
        uint128 refill;
        uint128 tokens;
        uint64 last;
    }

    uint256 private constant WAD = 1e18;
    uint256 public constant MAX_BUCKETS = 4;

    address public immutable bridge;
    address public immutable admin;
    address public immutable tuner;
    uint64 public immutable hold;
    uint64 public immutable loosenDelay;

    address public pauser;
    bool public paused;

    // Common-unit buckets in series; all refill from the same timestamp.
    Params[] internal params;
    uint128[] internal tokens;
    uint64 public lastRefill;
    uint128 public minCapacity; // smallest capacity among the common buckets (same slot as lastRefill)

    // A pending loosening of the common buckets.
    Params[] internal pendingParams;
    uint64 public pendingReadyAt; // 0 = none

    mapping(address => uint256) public weight; // common units per base unit, scaled by 1e18
    mapping(address => bool) public minted;
    mapping(address => AssetBucket) public assetBucket;
    mapping(address => Params) public pendingAsset;
    mapping(address => uint64) public pendingAssetReadyAt;

    uint64 public head;
    uint64 public nextId;
    mapping(uint256 => Request) public requests;

    event Queued(uint256 indexed id, address indexed asset, address indexed to, uint256 amount, uint256 value);
    event Executed(uint256 indexed id, uint256 value);
    event Cancelled(uint256 indexed id);
    event Dropped(uint256 indexed id);
    event Paused(address indexed by);
    event Unpaused(address indexed by);
    event Tightened();
    event LooseningProposed(uint64 readyAt);
    event LooseningApplied();
    event LooseningCancelled();
    event AssetTightened(address indexed asset);
    event AssetLooseningProposed(address indexed asset, uint64 readyAt);
    event AssetLooseningApplied(address indexed asset);

    error NotBridge();
    error NotAdmin();
    error NotTuner();
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
    error NothingPending();
    error TokenCallFailed();

    modifier onlyPauser() {
        if (msg.sender != pauser) revert NotPauser();
        _;
    }

    modifier onlyTuner() {
        if (msg.sender != tuner) revert NotTuner();
        _;
    }

    constructor(
        address bridge_,
        address admin_,
        address tuner_,
        address pauser_,
        Params[] memory params_,
        uint64 hold_,
        uint64 loosenDelay_
    ) {
        if (bridge_ == address(0) || admin_ == address(0) || tuner_ == address(0)) revert BadConfig();
        if (pauser_ == address(0) || pauser_ == bridge_ || pauser_ == admin_ || pauser_ == tuner_) revert BadConfig();
        if (params_.length == 0 || params_.length > MAX_BUCKETS || loosenDelay_ == 0) revert BadConfig();
        bridge = bridge_;
        admin = admin_;
        tuner = tuner_;
        pauser = pauser_;
        hold = hold_;
        loosenDelay = loosenDelay_;
        uint128 m = type(uint128).max;
        for (uint256 k = 0; k < params_.length; k++) {
            if (params_[k].capacity == 0) revert BadConfig();
            params.push(params_[k]);
            tokens.push(params_[k].capacity); // every bucket starts full
            if (params_[k].capacity < m) m = params_[k].capacity;
        }
        lastRefill = uint64(block.timestamp);
        minCapacity = m;
    }

    // ------------------------------------------------------------------ bridge side

    function requestRelease(address asset, address to, uint256 amount) external returns (uint256 id) {
        if (msg.sender != bridge) revert NotBridge();
        uint256 w = weight[asset];
        if (w == 0) revert BadAsset();
        if (amount == 0 || amount > type(uint128).max || to == address(0)) revert BadRequest();
        uint256 value = (amount * w + WAD - 1) / WAD;
        if (value > type(uint128).max) revert BadRequest();
        // a request above a bucket's capacity could never execute and would block the queue
        if (value > minCapacity) revert AboveCapacity();
        uint128 capA = assetBucket[asset].capacity;
        if (capA != 0 && amount > capA) revert AboveCapacity();
        id = nextId++;
        requests[id] = Request(asset, uint64(block.timestamp) + hold, Status.Queued, to, uint128(amount), uint128(value));
        emit Queued(id, asset, to, amount, value);
    }

    // ------------------------------------------------------------------ release

    /// Execute the oldest queued request once its hold has passed and every bucket, common and
    /// per-asset, holds its value. Anyone may call.
    function executeNext() external returns (uint256 id) {
        if (paused) revert IsPaused();
        uint256 end = nextId;
        id = head;
        while (id < end && requests[id].status == Status.Cancelled) id++;
        if (id == end) revert QueueEmpty();
        Request storage r = requests[id];
        if (block.timestamp < r.readyAt) revert NotReady();
        uint256 value = r.value;
        // a tightening after the request was queued can leave it above a bucket's capacity; it could
        // then never execute, so it is dropped (the bridge returns or resubmits it) and the queue moves on
        AssetBucket storage a = assetBucket[r.asset];
        if (value > minCapacity || (a.capacity != 0 && r.amount > a.capacity)) {
            r.status = Status.Cancelled;
            head = uint64(id + 1);
            emit Dropped(id);
            return id;
        }
        uint256 n = params.length;
        for (uint256 k = 0; k < n; k++) {
            uint256 avail = _available(k);
            if (value > avail) revert OverLimit();
            tokens[k] = uint128(avail - value);
        }
        lastRefill = uint64(block.timestamp);
        if (a.capacity != 0) {
            uint256 availA = _assetAvailable(a);
            if (r.amount > availA) revert OverLimit();
            a.tokens = uint128(availA - r.amount);
            a.last = uint64(block.timestamp);
        }
        r.status = Status.Executed;
        head = uint64(id + 1);
        emit Executed(id, value);
        if (minted[r.asset]) _call(r.asset, abi.encodeCall(IMintable.mint, (r.to, r.amount)));
        else _call(r.asset, abi.encodeCall(IERC20Min.transfer, (r.to, r.amount)));
    }

    function available(uint256 k) external view returns (uint256) {
        return _available(k);
    }

    function bucketCount() external view returns (uint256) {
        return params.length;
    }

    function bucket(uint256 k) external view returns (uint128 capacity, uint128 refill) {
        return (params[k].capacity, params[k].refill);
    }

    function _available(uint256 k) internal view returns (uint256) {
        Params memory p = params[k];
        uint256 t = uint256(tokens[k]) + uint256(p.refill) * (block.timestamp - lastRefill);
        return t < p.capacity ? t : p.capacity;
    }

    function _assetAvailable(AssetBucket storage a) internal view returns (uint256) {
        uint256 t = uint256(a.tokens) + uint256(a.refill) * (block.timestamp - a.last);
        return t < a.capacity ? t : a.capacity;
    }

    /// Bring every common bucket to the current time under the current parameters.
    function _settle() internal {
        uint256 n = params.length;
        for (uint256 k = 0; k < n; k++) {
            tokens[k] = uint128(_available(k));
        }
        lastRefill = uint64(block.timestamp);
    }

    // ------------------------------------------------------------------ tuner

    /// Propose new parameters for the common buckets. Every value that does not exceed the current
    /// one takes effect at once; if any value exceeds it, the whole proposal becomes effective only
    /// after `loosenDelay` (applyLoosening), and the pauser can cancel it before then. A new proposal
    /// replaces a pending one.
    function propose(Params[] calldata next) external onlyTuner {
        uint256 n = params.length;
        if (next.length != n) revert BadConfig();
        _settle();
        bool loosens = false;
        uint128 m = type(uint128).max;
        for (uint256 k = 0; k < n; k++) {
            if (next[k].capacity == 0) revert BadConfig();
            Params memory cur = params[k];
            if (next[k].capacity > cur.capacity || next[k].refill > cur.refill) loosens = true;
            uint128 cap = next[k].capacity < cur.capacity ? next[k].capacity : cur.capacity;
            uint128 ref = next[k].refill < cur.refill ? next[k].refill : cur.refill;
            params[k] = Params(cap, ref);
            if (tokens[k] > cap) tokens[k] = cap;
            if (cap < m) m = cap;
        }
        minCapacity = m;
        emit Tightened();
        delete pendingParams;
        if (loosens) {
            for (uint256 k = 0; k < n; k++) {
                pendingParams.push(next[k]);
            }
            pendingReadyAt = uint64(block.timestamp) + loosenDelay;
            emit LooseningProposed(pendingReadyAt);
        } else {
            pendingReadyAt = 0;
        }
    }

    /// Anyone may apply a pending loosening once its delay has passed.
    function applyLoosening() external {
        if (pendingReadyAt == 0) revert NothingPending();
        if (block.timestamp < pendingReadyAt) revert NotReady();
        _settle();
        uint256 n = params.length;
        uint128 m = type(uint128).max;
        for (uint256 k = 0; k < n; k++) {
            params[k] = pendingParams[k];
            if (tokens[k] > pendingParams[k].capacity) tokens[k] = pendingParams[k].capacity;
            if (pendingParams[k].capacity < m) m = pendingParams[k].capacity;
        }
        minCapacity = m;
        delete pendingParams;
        pendingReadyAt = 0;
        emit LooseningApplied();
    }

    /// The same rule for one asset's bucket (capacity 0 removes the per-asset limit, which counts as
    /// a loosening).
    function proposeAsset(address asset, Params calldata next) external onlyTuner {
        if (weight[asset] == 0) revert BadAsset();
        AssetBucket storage a = assetBucket[asset];
        bool loosens;
        if (a.capacity == 0) {
            // no limit yet: adding one tightens, so it starts full and takes effect at once
            if (next.capacity != 0) {
                assetBucket[asset] = AssetBucket(next.capacity, next.refill, next.capacity, uint64(block.timestamp));
                emit AssetTightened(asset);
            }
            loosens = false;
        } else {
            a.tokens = uint128(_assetAvailable(a));
            a.last = uint64(block.timestamp);
            loosens = next.capacity == 0 || next.capacity > a.capacity || next.refill > a.refill;
            if (next.capacity != 0) {
                uint128 cap = next.capacity < a.capacity ? next.capacity : a.capacity;
                uint128 ref = next.refill < a.refill ? next.refill : a.refill;
                a.capacity = cap;
                a.refill = ref;
                if (a.tokens > cap) a.tokens = cap;
                emit AssetTightened(asset);
            }
        }
        if (loosens) {
            pendingAsset[asset] = next;
            pendingAssetReadyAt[asset] = uint64(block.timestamp) + loosenDelay;
            emit AssetLooseningProposed(asset, pendingAssetReadyAt[asset]);
        } else {
            delete pendingAsset[asset];
            pendingAssetReadyAt[asset] = 0;
        }
    }

    function applyAssetLoosening(address asset) external {
        uint64 readyAt = pendingAssetReadyAt[asset];
        if (readyAt == 0) revert NothingPending();
        if (block.timestamp < readyAt) revert NotReady();
        AssetBucket storage a = assetBucket[asset];
        Params memory next = pendingAsset[asset];
        if (next.capacity == 0) {
            delete assetBucket[asset];
        } else {
            uint128 t = a.capacity == 0 ? next.capacity : uint128(_assetAvailable(a));
            if (t > next.capacity) t = next.capacity;
            assetBucket[asset] = AssetBucket(next.capacity, next.refill, t, uint64(block.timestamp));
        }
        delete pendingAsset[asset];
        pendingAssetReadyAt[asset] = 0;
        emit AssetLooseningApplied(asset);
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

    function cancel(uint256 id) external onlyPauser {
        Request storage r = requests[id];
        if (r.status != Status.Queued) revert NotQueued();
        r.status = Status.Cancelled;
        emit Cancelled(id);
    }

    /// The response cancels a pending loosening of the common buckets or of an asset's bucket.
    function cancelLoosening() external onlyPauser {
        if (pendingReadyAt == 0) revert NothingPending();
        delete pendingParams;
        pendingReadyAt = 0;
        emit LooseningCancelled();
    }

    function cancelAssetLoosening(address asset) external onlyPauser {
        if (pendingAssetReadyAt[asset] == 0) revert NothingPending();
        delete pendingAsset[asset];
        pendingAssetReadyAt[asset] = 0;
        emit LooseningCancelled();
    }

    // ------------------------------------------------------------------ admin

    function listAsset(address asset, uint256 weight_, bool minted_) external {
        if (msg.sender != admin) revert NotAdmin();
        if (weight_ == 0 || weight[asset] != 0 || asset.code.length == 0) revert BadAsset();
        weight[asset] = weight_;
        minted[asset] = minted_;
    }

    function _call(address token, bytes memory data) private {
        (bool ok, bytes memory ret) = token.call(data);
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TokenCallFailed();
    }
}
