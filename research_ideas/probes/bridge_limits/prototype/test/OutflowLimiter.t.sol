// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {OutflowLimiter} from "../src/OutflowLimiter.sol";
import {SlidingWindowCap} from "../src/Baselines.sol";
import {TestToken, WrappedToken, MockWeightSource} from "./mocks/Tokens.sol";

/// Common unit: USD with 18 decimals. B = 1,000 USD, R = 1 USD per second, H = 1 hour.
contract OutflowLimiterTest is Test {
    uint128 constant B = 1_000e18;
    uint128 constant R = 1e18;
    uint64 constant H = 1 hours;

    address bridge = makeAddr("bridge");
    address admin = makeAddr("admin");
    address pauser = makeAddr("pauser");
    address user = makeAddr("user");
    address rcpt = makeAddr("recipient");

    OutflowLimiter lim;
    MockWeightSource source;
    TestToken usd; // escrowed, 1 USD per unit
    TestToken eth; // escrowed, 2,000 USD per unit
    WrappedToken wrapped; // minted, 10 USD per unit

    function setUp() public {
        source = new MockWeightSource();
        lim = new OutflowLimiter(bridge, admin, pauser, source, B, R, H);
        usd = new TestToken();
        eth = new TestToken();
        wrapped = new WrappedToken(address(lim));
        vm.startPrank(admin);
        lim.listAsset(address(usd), 1e18, false);
        lim.listAsset(address(eth), 2_000e18, false);
        lim.listAsset(address(wrapped), 10e18, true);
        vm.stopPrank();
        usd.faucet(address(lim), 1_000_000e18);
        eth.faucet(address(lim), 1_000e18);
    }

    function _queue(address asset, uint256 amount) internal returns (uint256) {
        vm.prank(bridge);
        return lim.requestRelease(asset, rcpt, amount);
    }

    function _min(uint256 a, uint256 b) internal pure returns (uint256) {
        return a < b ? a : b;
    }

    // ------------------------------------------------------------------ bucket arithmetic

    function test_refillArithmetic() public {
        assertEq(lim.available(), B); // starts full
        _queue(address(usd), 600e18);
        skip(H);
        assertEq(lim.available(), B); // capped at B while idle
        lim.executeNext();
        assertEq(lim.available(), 400e18);
        skip(100);
        assertEq(lim.available(), 500e18);
        skip(499);
        assertEq(lim.available(), 999e18);
        skip(1);
        assertEq(lim.available(), B);
        skip(1 days);
        assertEq(lim.available(), B); // never above B
    }

    /// Two spends a and b separated by dt1: available = min(B, B - a + R dt1), then
    /// min(B, that - b + R dt2); b waits if it does not fit.
    function testFuzz_refill(uint256 a, uint256 b, uint256 dt1, uint256 dt2) public {
        a = bound(a, 1, B);
        b = bound(b, 1, B);
        dt1 = bound(dt1, 0, 2 days);
        dt2 = bound(dt2, 0, 2 days);
        _queue(address(usd), a);
        _queue(address(usd), b);
        skip(H);
        lim.executeNext();
        skip(dt1);
        uint256 avail = _min(B, B - a + R * dt1);
        assertEq(lim.available(), avail);
        if (b > avail) {
            vm.expectRevert(OutflowLimiter.OverLimit.selector);
            lim.executeNext();
            return;
        }
        lim.executeNext();
        skip(dt2);
        assertEq(lim.available(), _min(B, avail - b + R * dt2));
    }

    /// Thirty requests of 100 USD arrive at once from the quiet state. A keeper that executes every
    /// second releases nothing before H and then B + R (d - H) rounded down to whole requests, so
    /// the bound B + R max(d - H, 0) is met with equality at every multiple of 100 seconds.
    function test_burstFromFullBucketMeetsBound() public {
        uint256 tau = vm.getBlockTimestamp();
        for (uint256 k = 0; k < 30; k++) {
            _queue(address(usd), 100e18);
        }
        uint256 released;
        for (uint256 d = H - 10; d <= H + 2_000; d++) {
            vm.warp(tau + d);
            while (true) {
                try lim.executeNext() returns (uint256) {
                    released += 100e18;
                } catch {
                    break;
                }
            }
            uint256 cap = d < H ? 0 : B + R * (d - H);
            assertLe(released, cap);
            assertEq(released, _min(3_000e18, (cap / 100e18) * 100e18));
        }
        assertEq(released, 3_000e18);
    }

    // ------------------------------------------------------------------ hold and FIFO

    function test_holdIsEnforced() public {
        uint256 id = _queue(address(usd), 10e18);
        (, uint64 readyAt,,,,) = lim.requests(id);
        assertEq(readyAt, vm.getBlockTimestamp() + H);
        vm.warp(readyAt - 1);
        vm.expectRevert(OutflowLimiter.NotReady.selector);
        lim.executeNext();
        vm.warp(readyAt);
        lim.executeNext();
        assertEq(usd.balanceOf(rcpt), 10e18);
    }

    function test_fifo() public {
        uint256 a = _queue(address(usd), 800e18);
        uint256 b = _queue(address(usd), 300e18);
        uint256 c = _queue(address(usd), 100e18);
        skip(H);
        assertEq(lim.executeNext(), a); // 200 left
        vm.expectRevert(OutflowLimiter.OverLimit.selector); // c would fit, but b is ahead of it
        lim.executeNext();
        skip(100);
        assertEq(lim.executeNext(), b); // 0 left
        vm.expectRevert(OutflowLimiter.OverLimit.selector);
        lim.executeNext();
        skip(100);
        assertEq(lim.executeNext(), c);
        vm.expectRevert(OutflowLimiter.QueueEmpty.selector);
        lim.executeNext();
    }

    function test_cancelledRequestsAreSkipped() public {
        uint256 a = _queue(address(usd), 800e18);
        uint256 b = _queue(address(usd), 300e18);
        uint256 c = _queue(address(usd), 100e18);
        vm.prank(pauser);
        lim.cancel(b);
        skip(H);
        assertEq(lim.executeNext(), a);
        assertEq(lim.executeNext(), c); // b is skipped; c fits in the 200 left
        assertEq(usd.balanceOf(rcpt), 900e18);
    }

    // ------------------------------------------------------------------ pauser

    function test_pauserCancelsQueuedRequest() public {
        uint256 id = _queue(address(usd), 500e18);
        uint256 escrowBefore = usd.balanceOf(address(lim));
        vm.prank(pauser);
        lim.cancel(id);
        (,, OutflowLimiter.Status status,,,) = lim.requests(id);
        assertEq(uint8(status), uint8(OutflowLimiter.Status.Cancelled));
        skip(H);
        vm.expectRevert(OutflowLimiter.QueueEmpty.selector);
        lim.executeNext();
        assertEq(usd.balanceOf(address(lim)), escrowBefore); // funds never left the escrow
        assertEq(usd.balanceOf(rcpt), 0); // nothing is returned or paid to the requester
        assertEq(lim.available(), B); // no bucket tokens were used
        vm.expectRevert(OutflowLimiter.NotQueued.selector);
        vm.prank(pauser);
        lim.cancel(id);
    }

    function test_onlyPauserCancels() public {
        uint256 id = _queue(address(usd), 500e18);
        address[4] memory others = [bridge, admin, user, rcpt];
        for (uint256 k = 0; k < others.length; k++) {
            vm.expectRevert(OutflowLimiter.NotPauser.selector);
            vm.prank(others[k]);
            lim.cancel(id);
        }
        skip(H);
        lim.executeNext(); // the request is still live
        vm.expectRevert(OutflowLimiter.NotQueued.selector); // an executed request cannot be cancelled
        vm.prank(pauser);
        lim.cancel(id);
    }

    function testFuzz_onlyPauserCancels(address caller) public {
        vm.assume(caller != pauser);
        uint256 id = _queue(address(usd), 1e18);
        vm.expectRevert(OutflowLimiter.NotPauser.selector);
        vm.prank(caller);
        lim.cancel(id);
    }

    function test_pauseStopsExecution() public {
        _queue(address(usd), 10e18);
        skip(H);
        address[4] memory others = [bridge, admin, user, rcpt];
        for (uint256 k = 0; k < others.length; k++) {
            vm.expectRevert(OutflowLimiter.NotPauser.selector);
            vm.prank(others[k]);
            lim.pause();
        }
        vm.prank(pauser);
        lim.pause();
        vm.expectRevert(OutflowLimiter.IsPaused.selector);
        lim.executeNext();
        vm.expectRevert(OutflowLimiter.NotPauser.selector);
        vm.prank(admin);
        lim.unpause();
        vm.prank(pauser);
        lim.unpause();
        lim.executeNext();
        assertEq(usd.balanceOf(rcpt), 10e18);
    }

    function test_pauserIsIndependent() public {
        vm.expectRevert(OutflowLimiter.BadConfig.selector);
        new OutflowLimiter(bridge, admin, bridge, source, B, R, H);
        vm.expectRevert(OutflowLimiter.BadConfig.selector);
        new OutflowLimiter(bridge, admin, admin, source, B, R, H);
        vm.expectRevert(OutflowLimiter.NotPauser.selector); // the admin cannot move the role
        vm.prank(admin);
        lim.transferPauser(admin);
        vm.startPrank(pauser);
        vm.expectRevert(OutflowLimiter.BadConfig.selector);
        lim.transferPauser(bridge);
        vm.expectRevert(OutflowLimiter.BadConfig.selector);
        lim.transferPauser(admin);
        lim.transferPauser(user);
        vm.stopPrank();
        assertEq(lim.pauser(), user);
    }

    // ------------------------------------------------------------------ gross accounting

    function test_inflowsDoNotRefill() public {
        _queue(address(usd), 600e18);
        _queue(address(wrapped), 10e18); // 100 USD, minted
        skip(H);
        lim.executeNext();
        lim.executeNext();
        assertEq(lim.available(), 300e18);

        usd.faucet(rcpt, 50_000e18);
        vm.startPrank(rcpt);
        usd.approve(address(lim), type(uint256).max);
        lim.deposit(address(usd), 50_000e18, bytes32("dest")); // lock on the escrow side
        lim.deposit(address(wrapped), 10e18, bytes32("dest")); // burn on the mint side
        vm.stopPrank();

        assertEq(lim.available(), 300e18); // 50,100 USD of inflows add nothing
        assertEq(wrapped.totalSupply(), 0);
        skip(50);
        assertEq(lim.available(), 350e18); // only time refills
    }

    // ------------------------------------------------------------------ mint side and weights

    function test_mintPathSharesTheBucket() public {
        _queue(address(eth), 0.25e18); // 500 USD from escrow
        uint256 m = _queue(address(wrapped), 60e18); // 600 USD minted
        skip(H);
        lim.executeNext();
        assertEq(eth.balanceOf(rcpt), 0.25e18);
        assertEq(lim.available(), 500e18);
        vm.expectRevert(OutflowLimiter.OverLimit.selector); // the mint waits for refill
        lim.executeNext();
        assertEq(wrapped.totalSupply(), 0);
        skip(100);
        assertEq(lim.executeNext(), m);
        assertEq(wrapped.balanceOf(rcpt), 60e18);
        assertEq(wrapped.totalSupply(), 60e18);
        assertEq(lim.available(), 0);
        vm.expectRevert("not minter"); // no other mint path
        wrapped.mint(user, 1);
    }

    function test_valueWeighting() public {
        TestToken half = new TestToken(); // 0.5 USD per base unit
        vm.prank(admin);
        lim.listAsset(address(half), 0.5e18, false);
        uint256 id = _queue(address(half), 3); // 1.5 rounds up to 2
        (,,,,, uint128 value) = lim.requests(id);
        assertEq(value, 2);
        id = _queue(address(eth), 0.1e18);
        (,,,,, value) = lim.requests(id);
        assertEq(value, 200e18);
    }

    function test_requestChecks() public {
        vm.expectRevert(OutflowLimiter.NotBridge.selector);
        vm.prank(user);
        lim.requestRelease(address(usd), rcpt, 1e18);
        vm.startPrank(bridge);
        vm.expectRevert(OutflowLimiter.BadAsset.selector); // not listed
        lim.requestRelease(address(0xBEEF), rcpt, 1e18);
        vm.expectRevert(OutflowLimiter.AboveCapacity.selector); // 1,200 USD > B
        lim.requestRelease(address(eth), rcpt, 0.6e18);
        vm.expectRevert(OutflowLimiter.BadRequest.selector);
        lim.requestRelease(address(usd), rcpt, 0);
        vm.stopPrank();
    }

    function test_weightsFixedAndOnlyRise() public {
        TestToken other = new TestToken();
        vm.expectRevert(OutflowLimiter.NotAdmin.selector);
        vm.prank(bridge);
        lim.listAsset(address(other), 1e18, false);
        vm.expectRevert(OutflowLimiter.BadAsset.selector); // a listed weight cannot be replaced
        vm.prank(admin);
        lim.listAsset(address(usd), 0.5e18, false);
        source.set(address(usd), 0.9e18);
        vm.expectRevert(OutflowLimiter.BadAsset.selector); // the source cannot lower a weight
        lim.raiseWeight(address(usd));
        source.set(address(usd), 1.1e18);
        lim.raiseWeight(address(usd));
        assertEq(lim.weight(address(usd)), 1.1e18);
    }

    // ------------------------------------------------------------------ events

    function test_events() public {
        vm.expectEmit(true, true, true, true, address(lim));
        emit OutflowLimiter.Queued(0, address(usd), rcpt, 10e18, 10e18, uint64(vm.getBlockTimestamp() + H));
        _queue(address(usd), 10e18);
        _queue(address(usd), 20e18);
        skip(H);
        vm.expectEmit(true, true, true, true, address(lim));
        emit OutflowLimiter.Executed(0, 10e18, B - 10e18);
        lim.executeNext();
        vm.expectEmit(true, true, true, true, address(lim));
        emit OutflowLimiter.Cancelled(1);
        vm.prank(pauser);
        lim.cancel(1);
        vm.expectEmit(true, true, true, true, address(lim));
        emit OutflowLimiter.Paused(pauser);
        vm.prank(pauser);
        lim.pause();
        vm.expectEmit(true, true, true, true, address(lim));
        emit OutflowLimiter.Unpaused(pauser);
        vm.prank(pauser);
        lim.unpause();
    }
}

/// The sliding 24-hour cap used as a gas baseline: releases at once, up to the cap per window.
contract SlidingWindowCapTest is Test {
    address bridge = makeAddr("bridge");
    address admin = makeAddr("admin");
    address rcpt = makeAddr("recipient");
    SlidingWindowCap cap;
    TestToken usd;

    function setUp() public {
        cap = new SlidingWindowCap(bridge, admin, 1_000e18);
        usd = new TestToken();
        vm.prank(admin);
        cap.listAsset(address(usd), 1e18);
        usd.faucet(address(cap), 1_000_000e18);
    }

    function test_slidingWindow() public {
        uint256 t0 = vm.getBlockTimestamp();
        vm.startPrank(bridge);
        cap.release(address(usd), rcpt, 600e18); // released at once, no hold
        vm.warp(t0 + 1 hours);
        cap.release(address(usd), rcpt, 400e18);
        vm.expectRevert("cap reached");
        cap.release(address(usd), rcpt, 1);
        vm.warp(t0 + 24 hours); // the 600 has left the window
        cap.release(address(usd), rcpt, 600e18);
        vm.expectRevert("cap reached");
        cap.release(address(usd), rcpt, 1);
        vm.warp(t0 + 25 hours); // the 400 has left the window
        cap.release(address(usd), rcpt, 400e18);
        vm.stopPrank();
        assertEq(usd.balanceOf(rcpt), 2_000e18);
        assertEq(cap.windowSum(), 1_000e18);
        assertEq(cap.first(), 2);
    }
}
