// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20Min} from "./OutflowLimiter.sol";

/// Baseline 1: the bridge releases escrowed funds directly, with no limit.
contract PlainEscrow {
    address public immutable bridge;

    constructor(address bridge_) {
        require(bridge_ != address(0), "zero address");
        bridge = bridge_;
    }

    function release(address asset, address to, uint256 amount) external {
        require(msg.sender == bridge, "not bridge");
        require(to != address(0), "zero address");
        require(IERC20Min(asset).transfer(to, amount), "transfer failed");
    }
}

/// Baseline 2: immediate release under a sliding 24-hour cap on value released, with the same
/// fixed weights as the limiter. Each release is logged; entries that have left the window are
/// dropped from the running sum when the next release comes in.
contract SlidingWindowCap {
    struct Entry {
        uint64 time;
        uint192 value;
    }

    uint256 public constant WINDOW = 24 hours;
    uint256 private constant WAD = 1e18;

    address public immutable bridge;
    address public immutable admin;
    uint256 public immutable cap; // common units per 24 hours

    mapping(address => uint256) public weight;
    mapping(uint256 => Entry) public log;
    uint64 public first; // oldest entry still in the window
    uint64 public last; // next free entry
    uint128 public windowSum; // value released in the last 24 hours

    constructor(address bridge_, address admin_, uint256 cap_) {
        require(bridge_ != address(0) && admin_ != address(0), "zero address");
        bridge = bridge_;
        admin = admin_;
        cap = cap_;
    }

    function listAsset(address asset, uint256 weight_) external {
        require(msg.sender == admin, "not admin");
        require(weight_ != 0 && weight[asset] == 0, "bad asset");
        weight[asset] = weight_;
    }

    function release(address asset, address to, uint256 amount) external {
        require(msg.sender == bridge, "not bridge");
        require(to != address(0), "zero address");
        uint256 w = weight[asset];
        require(w != 0, "bad asset");
        uint256 value = (amount * w + WAD - 1) / WAD;
        uint256 sum = windowSum;
        uint64 i = first;
        uint64 end = last;
        while (i < end && log[i].time + WINDOW <= block.timestamp) {
            sum -= log[i].value;
            delete log[i];
            i++;
        }
        require(sum + value <= cap, "cap reached");
        log[end] = Entry(uint64(block.timestamp), uint192(value));
        first = i;
        last = end + 1;
        windowSum = uint128(sum + value);
        require(IERC20Min(asset).transfer(to, amount), "transfer failed");
    }
}
