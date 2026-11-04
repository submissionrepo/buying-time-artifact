// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {OutflowLimiter, IWeightSource} from "../src/OutflowLimiter.sol";
import {TestToken} from "./mocks/Tokens.sol";

/// Drives the limiter with arbitrary sequences of requests, waits, executions, pauses and
/// cancellations, starting from a full bucket and an empty queue. Each execution j (time t_j,
/// value v_j, request time q_j) is checked against
///   (a) hold:          t_j >= q_j + H
///   (b) every window:  v_i + ... + v_j <= B + R (t_j - t_i)            for all i <= j
///   (c) quiet start:   v_0 + ... + v_j <= B + R (t_j - tau - H)        tau = first request time
/// (c) is the bound "executed value within d of the first request <= B + R max(d - H, 0)";
/// (a) and (b) give the same bound for requests issued from any later time on.
contract Handler is Test {
    OutflowLimiter public immutable lim;
    TestToken public immutable usd;
    address public immutable bridge;
    address public immutable pauser;
    uint256 public immutable B;
    uint256 public immutable R;
    uint256 public immutable H;

    uint256 public tau;
    uint256 public executions;
    uint256 public violations;
    uint256 public maxFillBps; // max over j of (v_0 + ... + v_j) / (B + R (t_j - tau - H)), in bps
    uint256[] internal times;
    uint256[] internal values;

    constructor(OutflowLimiter lim_, TestToken usd_, address bridge_, address pauser_) {
        lim = lim_;
        usd = usd_;
        bridge = bridge_;
        pauser = pauser_;
        B = lim_.capacity();
        R = lim_.refillRate();
        H = lim_.hold();
    }

    /// One request; half of them small (at most B/50), half anywhere in [1, B].
    function request(uint256 seed) public {
        uint256 value = seed % 2 == 0 ? _bound(seed, 1, B / 50) : _bound(seed, 1, B);
        vm.prank(bridge);
        lim.requestRelease(address(usd), address(0xCAFE), value);
        if (tau == 0) tau = vm.getBlockTimestamp();
    }

    function burst(uint256 n, uint256 seed) public {
        n = _bound(n, 1, 20);
        for (uint256 k = 0; k < n; k++) {
            request(uint256(keccak256(abi.encode(seed, k))));
        }
    }

    /// Time passes with no keeper.
    function wait(uint256 dt) public {
        skip(_bound(dt, 0, 2 * H));
    }

    /// Time passes with a keeper that executes greedily every `step` seconds.
    function run(uint256 dt, uint256 step) public {
        dt = _bound(dt, 0, 2 * H);
        step = _bound(step, 1, 60);
        for (uint256 s = 0; s < dt; s += step) {
            skip(step);
            _executeAll();
        }
    }

    function executeAll() public {
        require(_executeAll() > 0, "nothing executed"); // counted as a revert in the call metrics
    }

    function pause() public {
        vm.prank(pauser);
        lim.pause();
    }

    function unpause() public {
        vm.prank(pauser);
        lim.unpause();
    }

    function cancel(uint256 k) public {
        uint256 lo = lim.head();
        uint256 hi = lim.nextId();
        require(hi > lo, "queue empty");
        vm.prank(pauser);
        lim.cancel(_bound(k, lo, hi - 1));
    }

    function _executeAll() internal returns (uint256 n) {
        while (true) {
            try lim.executeNext() returns (uint256 id) {
                (, uint64 readyAt,,,, uint128 value) = lim.requests(id);
                _check(readyAt - H, vm.getBlockTimestamp(), value);
                n++;
            } catch {
                break;
            }
        }
    }

    function _check(uint256 q, uint256 t, uint256 v) internal {
        executions++;
        if (t < q + H) violations++; // (a)
        times.push(t);
        values.push(v);
        uint256 sum;
        for (uint256 i = times.length; i > 0; i--) {
            sum += values[i - 1];
            if (sum > B + R * (t - times[i - 1])) violations++; // (b)
        }
        if (t < tau + H || sum > B + R * (t - tau - H)) {
            violations++; // (c)
        } else {
            uint256 fill = (sum * 10_000) / (B + R * (t - tau - H));
            if (fill > maxFillBps) maxFillBps = fill;
        }
    }
}

contract BoundInvariantTest is Test {
    uint128 constant B = 1_000e18; // 1,000 USD
    uint128 constant R = 1e18; // 1 USD per second
    uint64 constant H = 10 minutes;

    OutflowLimiter lim;
    Handler handler;

    function setUp() public {
        address bridge = makeAddr("bridge");
        address admin = makeAddr("admin");
        address pauser = makeAddr("pauser");
        lim = new OutflowLimiter(bridge, admin, pauser, IWeightSource(address(0)), B, R, H);
        TestToken usd = new TestToken();
        vm.prank(admin);
        lim.listAsset(address(usd), 1e18, false);
        usd.faucet(address(lim), type(uint128).max);
        handler = new Handler(lim, usd, bridge, pauser);

        bytes4[] memory selectors = new bytes4[](8);
        selectors[0] = Handler.request.selector;
        selectors[1] = Handler.burst.selector;
        selectors[2] = Handler.wait.selector;
        selectors[3] = Handler.run.selector;
        selectors[4] = Handler.executeAll.selector;
        selectors[5] = Handler.pause.selector;
        selectors[6] = Handler.unpause.selector;
        selectors[7] = Handler.cancel.selector;
        targetSelector(FuzzSelector({addr: address(handler), selectors: selectors}));
        targetContract(address(handler));
    }

    function invariant_releasesWithinBound() public view {
        assertEq(handler.violations(), 0);
    }

    function invariant_bucketAtMostCapacity() public view {
        assertLe(lim.available(), B);
    }

    /// One seeded schedule through the same handler (no pauses), giving counts that can be quoted.
    function test_seededScheduleWithinBound() public {
        for (uint256 k = 0; k < 300; k++) {
            uint256 r = uint256(keccak256(abi.encode("schedule", k)));
            uint256 action = r % 4;
            if (action == 0) handler.request(r >> 8);
            else if (action == 1) handler.burst(r >> 8, r >> 16);
            else handler.run(r >> 8, r >> 128);
        }
        assertEq(handler.violations(), 0);
        assertGt(handler.executions(), 100);
        console.log("executions checked:", handler.executions());
        console.log("max fill of B + R(d - H), bps:", handler.maxFillBps());
    }
}
