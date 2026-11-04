# OutflowLimiter prototype and gas table

- Date: 2026-10-16. Research prototype of the paper's construction (hold, then release against one value-weighted token bucket), with Foundry tests and a gas comparison. Not reviewed for production use. The tests are evidence about this implementation, not proofs of the theory statements.
- Code: `research_ideas/probes/bridge_limits/prototype/` (Foundry project; `lib/`, `out/`, `cache/`, `broadcast/` are git-ignored).
  - `src/OutflowLimiter.sol`: the limiter (about 170 lines without comments).
  - `src/Baselines.sol`: `PlainEscrow` (release with no limit) and `SlidingWindowCap` (immediate release under a sliding 24 h cap).
  - `test/OutflowLimiter.t.sol`: unit and fuzz tests; `test/Bound.invariant.t.sol`: stateful fuzz (invariant) test of the bound; `test/Gas.t.sol`: gas harness; `test/mocks/Tokens.sol`: minimal ERC20, mintable wrapped token, settable weight source.
  - `snapshots/GasBench.json`: gas written by the harness; `snapshots/anvil_receipts.txt`: receipt cross-check; `script/anvil_gas_check.sh`: produces the latter.
- Toolchain: forge 1.8.5 (commit 51a52c5), solc 0.8.30, optimizer on (200 runs), EVM version Prague, forge-std v1.17.0 (commit f3dae6e), anvil 1.8.5.
- Reproduce, from `prototype/`:

```
git clone --depth 1 --branch v1.17.0 https://github.com/foundry-rs/forge-std lib/forge-std
forge test                                 # all suites (31 tests)
forge test --match-contract GasBench       # gas only; rewrites snapshots/GasBench.json
bash script/anvil_gas_check.sh             # same steady state on anvil, gasUsed from receipts
```

## 1. Design

The contract sits at the release point of a bridge: it holds the escrowed assets (lock side) and is the only minter of wrapped assets (mint side). The bridge's verifier or messaging contract checks a cross-chain message and then calls the limiter; the limiter decides when value leaves.

| Element | Implementation |
|---|---|
| Roles | `bridge` (immutable): the only address that can queue a release. `admin` (immutable): lists assets. `pauser`: pauses, unpauses, cancels. The constructor requires the pauser to differ from bridge and admin; only the pauser can hand its role on, never to bridge or admin. The admin cannot pause, cancel, move the pauser role, or change B, R, H (immutables). |
| Bucket | One global token bucket in a common unit (USD with 18 decimals in the tests): capacity B, refill R per second, starts full. `available() = min(B, tokens + R (now - lastRefill))`, computed lazily at execution. Tokens, last refill time and the pause flag share one storage slot. |
| Value weighting | Each asset has a weight (common units per base unit, scaled by 1e18) set once by the admin at listing. `value = ceil(amount * weight / 1e18)`: rounding up, so no release is under-metered. No price feed is read on the request or execution path. |
| Optional weight adapter | `IWeightSource` stub. `raiseWeight(asset)` (anyone) copies a higher weight from the source; weights never fall, so a faulty source can slow an asset's releases but cannot loosen the limit. |
| Hold-then-release queue | `requestRelease(asset, to, amount)` (bridge only) stores the request with `readyAt = now + H`. `executeNext()` (anyone) takes the lowest pending id; it executes only if not paused, `now >= readyAt`, and `available() >= value`, then spends the tokens and transfers (escrow) or mints (wrapped). Otherwise it reverts and the request waits. Strict FIFO by id: a later request never passes an earlier one, even if it would fit. There is no release path that bypasses the bucket, and nothing is released automatically when the hold ends. |
| Capacity check | A request whose value exceeds B is rejected at queue time (it could never fit and would block the queue); larger transfers are split upstream, and the bucket meters the parts. |
| Pause and cancel | `pause()` stops execution (queueing continues). `cancel(id)` marks a queued request cancelled; it pays nothing to anyone, since escrowed funds never left and nothing was minted; `executeNext()` skips cancelled entries. |
| Gross accounting | `deposit(asset, amount, recipient)` locks escrowed assets or burns wrapped ones and never touches the bucket. |
| Events | `Queued(id, asset, to, amount, value, readyAt)`, `Executed(id, value, tokensLeft)`, `Cancelled(id)`, `Paused(by)`, `Unpaused(by)`, plus `Deposited`, `AssetListed`, `WeightRaised`, `PauserTransferred`. |

The bound the code enforces. Fix any time t0 and consider requests submitted at or after t0. None of them executes before t0 + H; every execution spends bucket tokens; the bucket holds at most B at t0 + H and gains R per second after that; deposits, cancellations and pauses add no tokens. Hence the value executed from these requests during [t0, t0 + d] is 0 for d < H and at most B + R (d - H) for d >= H, and never more than the value the limiter holds or can mint (W). This is the token-bucket instance of the paper's exposure curve: response min{W, B + R (d - H)^+}, a ramp after the hold rather than a cliff. The bound is in metered value (weights times amounts, rounded up), not market value.

## 2. Tests and outcomes

All 31 tests pass (`forge test`, 2026-10-16):

```
OutflowLimiterTest     17 passed  (2 fuzz tests, 1,000 runs each, seed 0x2026)
SlidingWindowCapTest    1 passed
BoundInvariantTest      2 passed  (invariant campaign: 256 runs x 100 calls = 25,600 calls,
                                   2 invariants; seeded schedule: 365 executions checked,
                                   largest fill 9,999 bps of B + R(d - H))
GasBench               11 passed
Ran 4 test suites: 31 tests passed, 0 failed, 0 skipped (31 total tests)
```

| Test | What it checks | Result |
|---|---|---|
| `test_refillArithmetic` | Starts full; after spending 600 of B = 1,000 at R = 1/s, available is 400, 500 after 100 s, 999 after 599 s, 1,000 after 600 s, still 1,000 a day later | pass |
| `testFuzz_refill` (1,000 runs) | Two spends a, b separated by fuzzed gaps: available = min(B, B - a + R dt1), then min(B, that - b + R dt2); b reverts with `OverLimit` when it does not fit | pass |
| `test_burstFromFullBucketMeetsBound` | Thirty 100-USD requests at once from a full bucket, keeper every second from d = H - 10 to H + 2,000 s: released value is 0 before H and exactly floor((B + R(d - H))/100) x 100 after, so it never exceeds B + R(d - H) and equals it at every multiple of 100 s | pass |
| `invariant_releasesWithinBound` (256 x 100 calls) | Random interleavings of request, burst (up to 20), wait, keeper run (greedy execution every 1-60 s), executeAll, pause, unpause, cancel, from a full bucket. Every execution j is checked for (a) hold: t_j >= q_j + H; (b) every window: v_i + ... + v_j <= B + R (t_j - t_i) for all i <= j; (c) from the first request at tau: v_0 + ... + v_j <= B + R (t_j - tau - H). (a) and (b) give the bound of section 1 for every start t0 | pass, 0 violations |
| `invariant_bucketAtMostCapacity` | available() <= B after every call | pass |
| `test_seededScheduleWithinBound` | 300 seeded actions through the same handler with an active keeper: 365 executions checked, 0 violations, cumulative release reached 99.99% of B + R(d - H) | pass |
| `test_holdIsEnforced` | `NotReady` at readyAt - 1, executes at readyAt | pass |
| `test_fifo` | Requests 800, 300, 100 with 200 tokens left: the 100 does not pass the 300; order 800, 300, 100 as tokens refill | pass |
| `test_cancelledRequestsAreSkipped` | A cancelled request is skipped and the next one executes | pass |
| `test_pauserCancelsQueuedRequest` | Status becomes Cancelled; escrow balance unchanged; requester receives nothing; no bucket tokens used; a second cancel reverts | pass |
| `test_onlyPauserCancels`, `testFuzz_onlyPauserCancels` (1,000 runs) | Bridge, admin, user, recipient, and any fuzzed address other than the pauser get `NotPauser`; an executed request cannot be cancelled | pass |
| `test_pauseStopsExecution` | Only the pauser pauses and unpauses; `IsPaused` while paused; executes after unpause | pass |
| `test_pauserIsIndependent` | Constructor rejects pauser = bridge or admin; admin cannot move the role; pauser cannot hand it to bridge or admin | pass |
| `test_inflowsDoNotRefill` | Locking 50,000 USD and burning 10 wrapped units (100 USD) leave available() unchanged; only time refills | pass |
| `test_mintPathSharesTheBucket` | 0.25 ETH from escrow (500 USD) and 60 wrapped units minted (600 USD) draw on one bucket; the mint waits 100 s for refill; wrapped supply grows only through the executed mint; direct mint by others reverts | pass |
| `test_valueWeighting` | value = ceil(amount x weight / 1e18): 3 base units at 0.5 USD each give 2; 0.1 ETH at 2,000 USD gives 200 USD | pass |
| `test_requestChecks` | Only the bridge queues; unlisted asset, zero amount, and value above B are rejected | pass |
| `test_weightsFixedAndOnlyRise` | Listing is admin-only and once per asset; the weight source can raise a weight but not lower it | pass |
| `test_events` | `Queued`, `Executed`, `Cancelled`, `Paused`, `Unpaused` with exact fields | pass |
| `test_slidingWindow` (baseline) | Releases at once up to the cap; an entry leaves the window 24 h after its release | pass |
| `GasBench` (11 tests) | Measurement harness for section 3 | pass |

Checks on the tests themselves:

- Seeded faults (applied one at a time to the source, then reverted): doubling the refill, shortening the hold by 60 s, and removing the cap at B each made `invariant_releasesWithinBound` and `test_seededScheduleWithinBound` fail; the burst test caught all three as well, and `invariant_bucketAtMostCapacity` caught the missing cap.
- forge 1.8.5 compiles `new` in tests through `vm.deployCode` by default (dynamic test linking). With that setting, `expectRevert` on a reverting constructor ended `test_pauserIsIndependent` early while reporting a pass. The project sets `dynamic_test_linking = false`; with it, the trace of every test outside the invariant campaign ends in `Stop`, so every assertion ran.

## 3. Gas

Conditions. Each figure is the gas of one transaction (21,000 base + calldata + execution, after the EIP-3529 refund), measured with `isolate = true` (every top-level call in a test is its own transaction with cold storage) and `vm.snapshotGasLastFrame`. Steady state: escrow and recipient already hold the token; the wrapped asset has supply; queue ids 0-2 executed and 3-5 queued and ready; the bucket partly refilled (99,000 USD plus 3,660 s of refill, about 141,361 USD available); the sliding window holds three entries (at T0, T0 + 1 h, T0 + 2 h). Parameters: B = 1,000,000 USD, R = B per day, H = 1 h; sliding cap 1,000,000 USD per 24 h; same fixed weights in limiter and sliding cap. Release amount 1,000 USD. The token is a minimal ERC20; a production token (proxy, allow-list checks) costs more per transfer and adds the same amount to every row that moves tokens.

| Operation | Gas (forge, isolated tx) | Gas (anvil receipt) |
|---|---:|---:|
| ERC20 transfer, holder to recipient (reference) | 34,344 | 34,356 |
| Baseline 1: plain escrow release (`PlainEscrow.release`) | 38,100 | 38,112 |
| Baseline 2: sliding 24 h cap release, no entry leaves the window | 71,438 | 71,450 |
| Baseline 2: sliding 24 h cap release, 1 entry leaves | 72,421 | 72,433 |
| Baseline 2: sliding 24 h cap release, 3 entries leave | 72,101 | 72,113 |
| Limiter: queue (`requestRelease`) | 100,716 | 100,728 |
| Limiter: execute, escrow transfer, with refill (`executeNext`) | 62,824 | 62,824 |
| Limiter: execute, mint | 62,404 | 62,404 |
| Limiter: execute, escrow, skipping one cancelled request | 65,179 | 65,179 |
| Limiter: cancel (pauser) | 30,032 | 30,032 |
| Limiter: pause (pauser) | 29,662 | 29,662 |

Cross-check. `script/anvil_gas_check.sh` rebuilds the same state on anvil (`--hardfork prague`), restores it with `evm_snapshot`/`evm_revert` before each measurement, and reads `gasUsed` from receipts; three runs gave identical output. Calls without address arguments match exactly. Calls with address arguments differ by +12 gas: the forge recipient address begins with a zero byte and the anvil addresses contain none, and calldata costs 16 gas per nonzero byte and 4 per zero byte.

Per release of an escrowed asset:

| Path | Transactions | Gas | Difference to plain release |
|---|---:|---:|---:|
| Plain escrow release | 1 | 38,100 | 0 |
| Sliding 24 h cap | 1 | 71,438 | +33,338 |
| OutflowLimiter, queue + execute | 2 | 163,540 | +125,440 |

In a deployment the queue call, like the two baseline releases, runs inside the bridge's own message-processing transaction, so all three drop the 21,000 base cost alike and the differences stay +33,338 and +125,440. The execution is a second transaction that anyone (a keeper or the recipient) sends after the hold; its 21,000 base cost is part of the +125,440. Mint-side releases cost about the same as escrow-side ones (62,404 against 62,824 for execution).

Where the gas goes (read off the gas schedule, not measured separately): queueing writes three fresh storage slots per request (3 x 22,100 = 66,300 gas, two thirds of the queue cost); execution reads them and updates two packed state slots (bucket and queue pointers) and one request slot. Two layouts would cut this and are not implemented: storing one hash per request (two fewer fresh slots, -44,200 gas at queueing, with the request fields passed as calldata at execution), and clearing a request's slots when it executes (refund of 4,800 gas per slot, capped at one fifth of the transaction's gas). The sliding cap's cost does not rise with expiring entries here because each deleted entry earns a refund, but its storage grows with the number of releases inside the window (one slot each), while the bucket's state is one slot.

## 4. Limits of the prototype

- FIFO blocks behind its head: a request whose token call keeps failing (for example, a recipient the token refuses) stops the queue until the pauser cancels it. A request above B is rejected rather than queued for the same reason.
- Weights are fixed at listing (they can only rise through the adapter), so the limit in market value moves with prices. B, R and H are immutable; changing them means a new deployment or a separate delayed governance path, which is not built here.
- The pauser's independence is checked only as address inequality on chain; whether the pauser keys sit with a party outside the bridge's verifier set is an off-chain fact.
- Cancellation leaves the funds in escrow; settling the requester's claim happens outside the contract.
- No size-based fast path: small requests wait the same H. Holds that depend on request size add no containment against split requests (see the paper on split requests), so the prototype does not have one.
- Token handling covers standard ERC20 tokens with or without a boolean return; fee-on-transfer and rebasing tokens are not handled.
