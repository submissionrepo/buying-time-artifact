// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {TunedLimiter} from "../src/TunedLimiter.sol";
import {TestToken} from "./mocks/Tokens.sol";

/// Unit and fuzz tests of TunedLimiter: buckets in series, the per-asset bucket, and the tuner's
/// tighten-now / loosen-later rule with the pauser's veto.
contract TunedLimiterTest is Test {
    uint64 constant H = 1 hours;
    uint64 constant DELAY = 2 days;
    uint256 constant T0 = 1_760_000_000;

    address bridge = makeAddr("bridge");
    address admin = makeAddr("admin");
    address tuner = makeAddr("tuner");
    address pauser = makeAddr("pauser");
    address rcpt = makeAddr("recipient");

    TunedLimiter lim;
    TestToken usd;
    TestToken eth;

    // Two buckets in series: one matched to short responses (small capacity, fast refill) and one
    // to long responses (larger capacity, slow refill); their minimum is concave.
    uint128 constant B1 = 50_000e18;
    uint128 constant R1 = uint128(uint256(50_000e18) / 1 hours);
    uint128 constant B2 = 200_000e18;
    uint128 constant R2 = uint128(uint256(10_000e18) / 1 hours);

    function _params2() internal pure returns (TunedLimiter.Params[] memory p) {
        p = new TunedLimiter.Params[](2);
        p[0] = TunedLimiter.Params(B1, R1);
        p[1] = TunedLimiter.Params(B2, R2);
    }

    function setUp() public {
        vm.warp(T0);
        lim = new TunedLimiter(bridge, admin, tuner, pauser, _params2(), H, DELAY);
        usd = new TestToken();
        eth = new TestToken();
        vm.startPrank(admin);
        lim.listAsset(address(usd), 1e18, false);
        lim.listAsset(address(eth), 1e18, false);
        vm.stopPrank();
        usd.faucet(address(lim), 1e30);
        eth.faucet(address(lim), 1e30);
    }

    function _minCurve(uint256 dt) internal pure returns (uint256) {
        uint256 a = uint256(B1) + uint256(R1) * dt;
        uint256 b = uint256(B2) + uint256(R2) * dt;
        return a < b ? a : b;
    }

    function _drain() internal returns (uint256 released) {
        while (true) {
            try lim.executeNext() {
                (,,,, uint128 amount,) = lim.requests(lim.head() - 1);
                released += amount;
            } catch {
                break;
            }
        }
    }

    /// Every window [t_i, t_j] of executions releases at most min_k (b_k + r_k (t_j - t_i)).
    function testFuzz_seriesBound(uint256 seed) public {
        vm.startPrank(bridge);
        for (uint256 k = 0; k < 120; k++) {
            uint256 v = 1 + (uint256(keccak256(abi.encode(seed, k))) % 9_000e18);
            lim.requestRelease(address(usd), rcpt, v);
        }
        vm.stopPrank();
        uint256 steps = 24;
        uint256[] memory times = new uint256[](steps);
        uint256[] memory cum = new uint256[](steps + 1);
        skip(H);
        for (uint256 s = 0; s < steps; s++) {
            skip(uint256(keccak256(abi.encode(seed, "dt", s))) % (2 hours));
            times[s] = block.timestamp;
            cum[s + 1] = cum[s] + _drain();
        }
        for (uint256 i = 0; i < steps; i++) {
            for (uint256 j = i; j < steps; j++) {
                uint256 rel = cum[j + 1] - cum[i];
                assertLe(rel, _minCurve(times[j] - times[i]), "window above the series curve");
            }
        }
    }

    function test_perAssetBucketLimitsOnlyItsAsset() public {
        vm.prank(tuner);
        lim.proposeAsset(address(eth), TunedLimiter.Params(10_000e18, uint128(uint256(1_000e18) / 1 hours)));
        assertEq(lim.pendingAssetReadyAt(address(eth)), 0); // adding a limit takes effect at once
        vm.startPrank(bridge);
        lim.requestRelease(address(eth), rcpt, 8_000e18); // id 0
        lim.requestRelease(address(eth), rcpt, 8_000e18); // id 1: exceeds the per-asset bucket
        lim.requestRelease(address(usd), rcpt, 8_000e18); // id 2
        vm.stopPrank();
        skip(H);
        lim.executeNext();
        vm.expectRevert(TunedLimiter.OverLimit.selector);
        lim.executeNext();
        // after enough refill of the eth bucket (6,000 units in six hours, less rounding), id 1 and then id 2 pass
        skip(7 hours);
        lim.executeNext();
        lim.executeNext();
        assertEq(lim.head(), 3);
    }

    /// A request above the smallest bucket, or above its asset's bucket, could never execute: rejected.
    function test_rejectsRequestAboveCapacity() public {
        vm.startPrank(bridge);
        vm.expectRevert(TunedLimiter.AboveCapacity.selector);
        lim.requestRelease(address(usd), rcpt, uint256(B1) + 1);
        lim.requestRelease(address(usd), rcpt, B1); // exactly the capacity fits
        vm.stopPrank();
        vm.prank(tuner);
        lim.proposeAsset(address(eth), TunedLimiter.Params(10_000e18, uint128(uint256(1_000e18) / 1 hours)));
        vm.prank(bridge);
        vm.expectRevert(TunedLimiter.AboveCapacity.selector);
        lim.requestRelease(address(eth), rcpt, 10_000e18 + 1);
    }

    /// A tightening that leaves a queued request above a bucket's capacity cannot block the queue:
    /// the request is dropped when it reaches the head and the next one executes.
    function test_tighteningDropsUnexecutableHead() public {
        vm.startPrank(bridge);
        lim.requestRelease(address(usd), rcpt, 40_000e18); // id 0
        lim.requestRelease(address(usd), rcpt, 5_000e18); // id 1
        vm.stopPrank();
        TunedLimiter.Params[] memory p = _params2();
        p[0].capacity = 20_000e18;
        vm.prank(tuner);
        lim.propose(p);
        skip(H);
        vm.expectEmit(true, false, false, false, address(lim));
        emit TunedLimiter.Dropped(0);
        lim.executeNext();
        (,, TunedLimiter.Status s0,,,) = lim.requests(0);
        assertEq(uint256(s0), uint256(TunedLimiter.Status.Cancelled));
        lim.executeNext();
        (,, TunedLimiter.Status s1,,,) = lim.requests(1);
        assertEq(uint256(s1), uint256(TunedLimiter.Status.Executed));
        assertEq(usd.balanceOf(rcpt), 5_000e18);
    }

    function test_tighteningTakesEffectAtOnce() public {
        TunedLimiter.Params[] memory p = _params2();
        p[0].capacity = 10_000e18;
        vm.prank(tuner);
        lim.propose(p);
        (uint128 cap,) = lim.bucket(0);
        assertEq(cap, 10_000e18);
        assertEq(lim.available(0), 10_000e18);
        assertEq(lim.pendingReadyAt(), 0);
    }

    function test_looseningWaitsForTheDelay() public {
        TunedLimiter.Params[] memory p = _params2();
        p[0].capacity = 5 * B1;
        vm.prank(tuner);
        lim.propose(p);
        (uint128 cap,) = lim.bucket(0);
        assertEq(cap, B1);
        assertEq(lim.pendingReadyAt(), T0 + DELAY);
        vm.expectRevert(TunedLimiter.NotReady.selector);
        lim.applyLoosening();
        skip(DELAY);
        lim.applyLoosening();
        (cap,) = lim.bucket(0);
        assertEq(cap, 5 * B1);
    }

    function test_mixedProposalTightensNowAndLoosensLater() public {
        TunedLimiter.Params[] memory p = _params2();
        p[0].capacity = B1 / 2; // tighter
        p[1].refill = 2 * R2; // looser
        vm.prank(tuner);
        lim.propose(p);
        (uint128 c0,) = lim.bucket(0);
        (, uint128 r1) = lim.bucket(1);
        assertEq(c0, B1 / 2);
        assertEq(r1, R2);
        skip(DELAY);
        lim.applyLoosening();
        (, r1) = lim.bucket(1);
        assertEq(r1, 2 * R2);
    }

    function test_pauserCancelsPendingLoosening() public {
        TunedLimiter.Params[] memory p = _params2();
        p[1].capacity = 10 * B2;
        vm.prank(tuner);
        lim.propose(p);
        vm.prank(pauser);
        lim.cancelLoosening();
        skip(DELAY);
        vm.expectRevert(TunedLimiter.NothingPending.selector);
        lim.applyLoosening();
        (uint128 cap,) = lim.bucket(1);
        assertEq(cap, B2);
    }

    function test_removingAnAssetLimitIsALoosening() public {
        vm.startPrank(tuner);
        lim.proposeAsset(address(eth), TunedLimiter.Params(10_000e18, 1e18));
        lim.proposeAsset(address(eth), TunedLimiter.Params(0, 0));
        vm.stopPrank();
        (uint128 cap,,,) = lim.assetBucket(address(eth));
        assertEq(cap, 10_000e18);
        vm.prank(pauser);
        lim.cancelAssetLoosening(address(eth));
        skip(DELAY);
        vm.expectRevert(TunedLimiter.NothingPending.selector);
        lim.applyAssetLoosening(address(eth));
    }

    function test_onlyTunerProposes() public {
        TunedLimiter.Params[] memory p = _params2();
        vm.expectRevert(TunedLimiter.NotTuner.selector);
        lim.propose(p);
        vm.prank(admin);
        vm.expectRevert(TunedLimiter.NotTuner.selector);
        lim.propose(p);
    }

    function test_constructorRejectsDependentPauser() public {
        vm.expectRevert(TunedLimiter.BadConfig.selector);
        new TunedLimiter(bridge, admin, tuner, tuner, _params2(), H, DELAY);
        vm.expectRevert(TunedLimiter.BadConfig.selector);
        new TunedLimiter(bridge, admin, tuner, pauser, _params2(), H, 0);
    }

    function test_holdAndPause() public {
        vm.prank(bridge);
        lim.requestRelease(address(usd), rcpt, 1_000e18);
        vm.expectRevert(TunedLimiter.NotReady.selector);
        lim.executeNext();
        skip(H);
        vm.prank(pauser);
        lim.pause();
        vm.expectRevert(TunedLimiter.IsPaused.selector);
        lim.executeNext();
        vm.prank(pauser);
        lim.cancel(0);
        vm.prank(pauser);
        lim.unpause();
        vm.expectRevert(TunedLimiter.QueueEmpty.selector);
        lim.executeNext();
    }
}
