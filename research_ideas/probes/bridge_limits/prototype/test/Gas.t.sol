// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {OutflowLimiter, IWeightSource} from "../src/OutflowLimiter.sol";
import {PlainEscrow, SlidingWindowCap} from "../src/Baselines.sol";
import {TestToken, WrappedToken} from "./mocks/Tokens.sol";

/// Gas of single operations in steady state. Each test measures its last call. Run in isolation
/// mode, where every top-level call is its own transaction with cold storage:
///     forge test --match-contract GasBench --isolate
/// Steady state: the escrow and the recipient already hold the asset, the wrapped asset has
/// supply, the queue has history, and the sliding window already holds three entries.
/// Parameters: B = 1,000,000 USD, R = B per day, H = 1 hour; sliding cap 1,000,000 USD per 24 h.
contract GasBench is Test {
    uint128 constant B = 1_000_000e18;
    uint128 constant R = uint128(B / 1 days);
    uint64 constant H = 1 hours;
    uint256 constant T0 = 1_760_000_000;

    address bridge = makeAddr("bridge");
    address admin = makeAddr("admin");
    address pauser = makeAddr("pauser");
    address rcpt = makeAddr("recipient");
    address holder = makeAddr("holder");

    OutflowLimiter lim;
    PlainEscrow plain;
    SlidingWindowCap window;
    TestToken usd;
    WrappedToken wrapped;

    function setUp() public {
        vm.warp(T0);
        lim = new OutflowLimiter(bridge, admin, pauser, IWeightSource(address(0)), B, R, H);
        plain = new PlainEscrow(bridge);
        window = new SlidingWindowCap(bridge, admin, B);
        usd = new TestToken();
        wrapped = new WrappedToken(address(lim));
        vm.startPrank(admin);
        lim.listAsset(address(usd), 1e18, false);
        lim.listAsset(address(wrapped), 1e18, true);
        window.listAsset(address(usd), 1e18);
        vm.stopPrank();
        usd.faucet(address(lim), 1e27);
        usd.faucet(address(plain), 1e27);
        usd.faucet(address(window), 1e27);
        usd.faucet(holder, 1e27);
        usd.faucet(rcpt, 1e18);

        // Limiter: ids 0-2 are released at T0 + H, leaving 99,000 USD in the bucket; ids 3-5 are
        // queued then and become executable at T0 + 2H. Window: entries at T0, T0 + H, T0 + 2H.
        vm.startPrank(bridge);
        lim.requestRelease(address(usd), rcpt, 450_000e18);
        lim.requestRelease(address(usd), rcpt, 450_000e18);
        lim.requestRelease(address(wrapped), rcpt, 1_000e18);
        window.release(address(usd), rcpt, 1_000e18);
        vm.stopPrank();
        vm.warp(T0 + H);
        lim.executeNext();
        lim.executeNext();
        lim.executeNext();
        vm.startPrank(bridge);
        lim.requestRelease(address(usd), rcpt, 1_000e18); // id 3, escrow
        lim.requestRelease(address(wrapped), rcpt, 1_000e18); // id 4, mint
        lim.requestRelease(address(usd), rcpt, 1_000e18); // id 5, escrow
        window.release(address(usd), rcpt, 1_000e18);
        vm.stopPrank();
        vm.warp(T0 + 2 * H);
        vm.prank(bridge);
        window.release(address(usd), rcpt, 1_000e18);
        vm.warp(T0 + 2 * H + 60); // the bucket has refilled for H + 60 s since the last execution
    }

    // ------------------------------------------------------------------ OutflowLimiter

    function test_limiterQueue() public {
        vm.prank(bridge);
        lim.requestRelease(address(usd), rcpt, 1_000e18);
        vm.snapshotGasLastFrame("limiter_queue");
    }

    function test_limiterExecuteEscrow() public {
        lim.executeNext(); // id 3
        vm.snapshotGasLastFrame("limiter_execute_escrow");
    }

    function test_limiterExecuteMint() public {
        lim.executeNext(); // id 3
        vm.warp(T0 + 2 * H + 120);
        lim.executeNext(); // id 4
        vm.snapshotGasLastFrame("limiter_execute_mint");
    }

    function test_limiterExecuteSkippingCancelled() public {
        vm.prank(pauser);
        lim.cancel(4);
        lim.executeNext(); // id 3
        vm.warp(T0 + 2 * H + 120);
        lim.executeNext(); // skips id 4, executes id 5
        vm.snapshotGasLastFrame("limiter_execute_escrow_skip1");
    }

    function test_limiterCancel() public {
        vm.prank(pauser);
        lim.cancel(5);
        vm.snapshotGasLastFrame("limiter_cancel");
    }

    function test_limiterPause() public {
        vm.prank(pauser);
        lim.pause();
        vm.snapshotGasLastFrame("limiter_pause");
    }

    // ------------------------------------------------------------------ baselines

    function test_tokenTransfer() public {
        vm.prank(holder);
        usd.transfer(rcpt, 1_000e18);
        vm.snapshotGasLastFrame("token_transfer");
    }

    function test_plainRelease() public {
        vm.prank(bridge);
        plain.release(address(usd), rcpt, 1_000e18);
        vm.snapshotGasLastFrame("plain_release");
    }

    function test_windowRelease() public {
        vm.prank(bridge);
        window.release(address(usd), rcpt, 1_000e18);
        vm.snapshotGasLastFrame("window_release");
    }

    function test_windowReleaseExpiringOne() public {
        vm.warp(T0 + 1 days + 60); // the entry from T0 has left the window
        vm.prank(bridge);
        window.release(address(usd), rcpt, 1_000e18);
        vm.snapshotGasLastFrame("window_release_expire1");
    }

    function test_windowReleaseExpiringThree() public {
        vm.warp(T0 + 1 days + 2 * H + 60); // all three entries have left the window
        vm.prank(bridge);
        window.release(address(usd), rcpt, 1_000e18);
        vm.snapshotGasLastFrame("window_release_expire3");
    }
}
