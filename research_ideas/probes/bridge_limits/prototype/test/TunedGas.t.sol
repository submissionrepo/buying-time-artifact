// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {TunedLimiter} from "../src/TunedLimiter.sol";
import {TestToken} from "./mocks/Tokens.sol";

/// Gas of TunedLimiter in steady state, in isolation mode like GasBench (every top-level call its
/// own transaction with cold storage):
///     forge test --match-contract TunedGasBench --isolate
/// Three deployments: one bucket, four buckets in series, and four buckets plus a per-asset bucket
/// on the released asset. Each has executed three releases and holds three more, ready to execute.
contract TunedGasBench is Test {
    uint64 constant H = 1 hours;
    uint256 constant T0 = 1_760_000_000;

    address bridge = makeAddr("bridge");
    address admin = makeAddr("admin");
    address tuner = makeAddr("tuner");
    address pauser = makeAddr("pauser");
    address rcpt = makeAddr("recipient");

    TunedLimiter one;
    TunedLimiter four;
    TunedLimiter fourAsset;
    TestToken usd;

    function _params(uint256 k) internal pure returns (TunedLimiter.Params[] memory p) {
        p = new TunedLimiter.Params[](k);
        // buckets matched to 1 h, 6 h, 1 day and 1 week of a traffic of about 1M USD per day
        uint128[4] memory caps = [uint128(150_000e18), 400_000e18, 1_000_000e18, 3_000_000e18];
        uint128[4] memory hrs = [uint128(1), 6, 24, 168];
        for (uint256 i = 0; i < k; i++) {
            p[i] = TunedLimiter.Params(caps[i], uint128(uint256(caps[i]) / (hrs[i] * 1 hours)));
        }
    }

    function _deploy(uint256 k, bool asset) internal returns (TunedLimiter lim) {
        lim = new TunedLimiter(bridge, admin, tuner, pauser, _params(k), H, 2 days);
        vm.prank(admin);
        lim.listAsset(address(usd), 1e18, false);
        if (asset) {
            vm.prank(tuner);
            lim.proposeAsset(address(usd), TunedLimiter.Params(500_000e18, uint128(uint256(500_000e18) / 1 days)));
        }
        usd.faucet(address(lim), 1e27);
        vm.startPrank(bridge);
        for (uint256 i = 0; i < 6; i++) {
            lim.requestRelease(address(usd), rcpt, 1_000e18);
        }
        vm.stopPrank();
    }

    function setUp() public {
        vm.warp(T0);
        usd = new TestToken();
        usd.faucet(rcpt, 1e18);
        one = _deploy(1, false);
        four = _deploy(4, false);
        fourAsset = _deploy(4, true);
        vm.warp(T0 + H);
        for (uint256 i = 0; i < 3; i++) {
            one.executeNext();
            four.executeNext();
            fourAsset.executeNext();
        }
        vm.warp(T0 + H + 60);
    }

    function test_tunedQueue() public {
        vm.prank(bridge);
        four.requestRelease(address(usd), rcpt, 1_000e18);
        vm.snapshotGasLastFrame("tuned_queue");
    }

    function test_tunedExecuteOne() public {
        one.executeNext();
        vm.snapshotGasLastFrame("tuned_execute_k1");
    }

    function test_tunedExecuteFour() public {
        four.executeNext();
        vm.snapshotGasLastFrame("tuned_execute_k4");
    }

    function test_tunedExecuteFourAsset() public {
        fourAsset.executeNext();
        vm.snapshotGasLastFrame("tuned_execute_k4_asset");
    }

    function test_tunedTighten() public {
        TunedLimiter.Params[] memory p = _params(4);
        p[0].capacity = 100_000e18;
        vm.prank(tuner);
        four.propose(p);
        vm.snapshotGasLastFrame("tuned_tighten_k4");
    }
}
