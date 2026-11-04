# Deployed outflow-limit rules: behaviour established from source code

Prepared 2026-10-16 for the paper on bridge withdrawal limits. These are reading notes on code, not verified statements; Table 1 of the paper (tex/rules.csv) is compiled from Section 3.

## 0. Conventions

- **Release.** Assets leave custody, or are minted, on the chain where value exits. An **unbacked release** is a release authorized by a message that no matching deposit or burn stands behind. Three upstream faults produce one: a faulty source-chain contract, a faulty verifier set, or a faulty release contract.
- **Verifier set.** The parties whose attestations authorize a cross-chain message: Wormhole Guardians, CCIP DONs and RMN, LayerZero DVNs, Axelar verifiers, Hyperlane validators, Circle attesters, Ronin operators, the Celer SGN, the Gnosis bridge validators, THORChain nodes. For the rollup bridges (Linea, StarkGate, Taiko), a validity proof plays this role.
- **Enforcement stage.** One of four places:
  - *verifier*: off-chain, in the software that decides whether to attest;
  - *source send*: on-chain where the user deposits or burns;
  - *destination release*: on-chain where funds are unlocked or minted;
  - *token*: inside the token contract.
- **Shape.** The response of cumulative release to an unbounded queue of unbacked requests:
  - *ramp*: rate-bounded (token bucket, or a cap per fixed window);
  - *geometric*: each window's allowance is a share of the current balance;
  - *cliff*: everything queued is released after a fixed deadline;
  - *bounded*: a cumulative cap that holds until an independent review.
- **Counted inflow.** Under net accounting, a flow that restores release capacity. Its "cost" says what such a flow requires:
  - a real deposit or burn of the same token on the releasing chain; or
  - a message attested by the verifier set.
- **Line numbers.** Line numbers (L) refer to the file at the pinned commit in §1. Quotes are verbatim, and "…" marks an elision.

## 1. Sources (cloned or extracted at the commits below; not included in the artifact)

| Local directory | Remote | Commit (commit date) | Used for |
|---|---|---|---|
| `wormhole-foundation__wormhole` | github.com/wormhole-foundation/wormhole | `bb5957f321b0a9d168f52e906699ee77baa82a28` (2026-10-13) | Governor, Global Accountant, Notary |
| `wormhole-foundation_native-token-transfers` | github.com/wormhole-foundation/native-token-transfers | `9fa9136f20847a2dc83c46249f467ea72e4ebec9` (2026-10-14) | NTT |
| `smartcontractkit__chainlink-ccip` | github.com/smartcontractkit/chainlink-ccip | `055a7e78d705b8e1857b235cc3b6ab39f18ee1f8` (2026-10-15; pools report `"BurnMintTokenPool 2.0.0"`) | CCIP v2.0 |
| `smartcontractkit__chainlink-ccip_v1.6.4` | same | `bccdd15b734ea6c0e6d1b3d36c482e64ced2d441` (2025-11-17; OffRamp reports `"OffRamp 1.6.2-dev"`) | CCIP v1.6 |
| `LayerZero-Labs__devtools` | github.com/LayerZero-Labs/devtools | `4973ba8bef7b0fdf7268469abea3ea50dbd4bbd8` (2026-06-30) | OApp `RateLimiter` |
| `LayerZero-Labs__LayerZero-v2` | github.com/LayerZero-Labs/LayerZero-v2 | `9c741e7f9790639537b1710a203bcdfd73b0b9ac` (2026-02-27) | EndpointV2 retry and message-clearing powers |
| `npm__layerzerolabs__utils-upgradeable-evm-contracts-1.2.83`, `npm__layerzerolabs__oft-upgradeable-evm-contracts-1.2.83` | npm `@layerzerolabs/…@1.2.83` (no git hash in package; tarball sha256 prefixes `dfd839396c0533e5`, `5aca2446d21f010e`) | version 1.2.83 | Stablecoin/RWA OFT rate limiter, pause by ID |
| `axelarnetwork_interchain-token-service` | github.com/axelarnetwork/interchain-token-service | `0f4b03706c79ed9c364edd080aca4ae23a7e3642` (2026-10-06) | ITS flow limits |
| `axelarnetwork_axelar-cgp-solidity` | github.com/axelarnetwork/axelar-cgp-solidity | `43ec407499434448c91da71f031e618d3ed7578a` (2026-08-12) | legacy gateway mint limit |
| `axelarnetwork__axelar-amplifier` (sparse) | github.com/axelarnetwork/axelar-amplifier | `6703b92bc4682b1320b06fda7c3168bbcb7bac5c` (2026-09-30) | ITS Hub supply tracking |
| `axelarnetwork__axelar-core` (sparse, plus a `_v1.2.0` file copy) | github.com/axelarnetwork/axelar-core | `aaa8a4e1e4af2600d7c3614ae97416aeff5979ba` (2026-10-14) | network-level transfer rate limit (historical) |
| `hyperlane-xyz__hyperlane-monorepo` | github.com/hyperlane-xyz/hyperlane-monorepo | `e3eee02129b5fd302daf0f44c9816a9b0e7b80a1` (2026-10-15) | RateLimited hook and ISM, net-flow and delayed-flow variants |
| `circlefin_evm-cctp-contracts` | github.com/circlefin/evm-cctp-contracts | `a92a2b4e7e6ef99bf0b05dca71780f5ec190e729` (2026-06-18) | CCTP |
| `circlefin__stablecoin-evm` (**cloned in this pass**, sparse `contracts/v1`) | github.com/circlefin/stablecoin-evm | `fc85788bc7c23cefe3df1a757133048bfddadeaa` (2026-08-12) | USDC minter allowance |
| `Consensys__linea-monorepo` (sparse) | github.com/Consensys/linea-monorepo | `7952d16daaf5d0c0233859e7d65812c3a3299552` (2026-10-15) | Linea message service |
| `starknet-io_starkgate-contracts` | github.com/starknet-io/starkgate-contracts | `07e11c39119a10d5742735be5b1d51894ebf5311` (2026-03-23, branch SN-v0.14.2) | StarkGate |
| `axieinfinity__ronin-bridge-contracts` | github.com/axieinfinity/ronin-bridge-contracts | `b037428593c5d79808e7e34a808704a64d8b18a9` (2024-03-05, branch mainnet) | Ronin |
| `axieinfinity_ronin-dpos-contracts` | github.com/axieinfinity/ronin-dpos-contracts | `f301e1a624289f93a8312f348c83c7de7a2d222c` (2023-10-31) | cross-check: `_reachedWithdrawalLimit` is identical |
| `celer-network_sgn-v2-contracts` | github.com/celer-network/sgn-v2-contracts | `dd60f9563d84127cd5cd33adcbe1df0fc14090e3` (2026-05-25) | cBridge |
| `gnosischain_omnibridge` | github.com/gnosischain/omnibridge | `ccd9003d99eb0bda86e7f3320d08804f2f98cff8` (2026-09-09) | OmniBridge |
| `gnosischain__tokenbridge-contracts` | github.com/gnosischain/tokenbridge-contracts | `47873407e00a147fec49d801f7159151d8fe9a33` (2024-10-14) | AMB, xDai bridge |
| `bnb-chain__bsc-genesis-contract` | github.com/bnb-chain/bsc-genesis-contract | master `84641812a013eda1593e058aeed4dc116c7746eb` (2026-09-11); **tag v1.1.9 `d647bfe8d3fc4ecf1280a4d892914c72619f22e6` (2023-05-05), fetched in this pass** | BEP-171 (v1.1.9), current token-recovery lock (master) |
| `defi-wonderland_xERC20` | github.com/defi-wonderland/xERC20 | `da2afabdeb1bad9ccda2f6eb928cd99e852530be` (2025-02-13) | xERC20 reference |
| `taikoxyz__taiko-mono` | github.com/taikoxyz/taiko-mono | `719449773217e277782b4d60e0b225e17b9a67f3` (2026-10-15) | QuotaManager |
| `thorchain__thornode` (sparse, blob-less) | gitlab.com/thorchain/thornode | `8eb2d08c6aa099005b33a322aa01278b9db32db7` (2026-10-15, develop) | outbound delay, solvency halt |
| `DeFi-Circuit-Breaker_v1-core` | github.com/DeFi-Circuit-Breaker/v1-core | `3960a0590ec3ee405b15273d9d4dc04f62fb5f9d` (2023-07-10) | ERC-7265 reference |

**On-chain reads in this pass.**

- Setup: `eth_call` at Ethereum blocks 26,201,369 to 26,201,371 (2026-10-16 00:01 UTC), RPC `ethereum-rpc.publicnode.com`, via `ethcall_lib.py` in this directory.
- USDC `[contract address omitted]`, `minterAllowance(address)`:
  - CCTP TokenMinter V1 `[contract address omitted]` = **108,188,601.02 USDC**;
  - TokenMinter V2 `[contract address omitted]` = **1,168,695,417.66 USDC**;
  - `isMinter` is true for both.
- StarkGate `getRemainingIntradayAllowance(token)` returns **uint256.max**, meaning the limit is not applied, on:
  - the ETH bridge `[contract address omitted]` (`identify()` = "StarkWare_StarknetEthBridge_2.0_4", token `0x…455448`);
  - the STRK bridge `[contract address omitted]` (`identify()` = "StarkWare_StarknetERC20Bridge_2.0_5", token `[contract address omitted]`).

Deployment equivalence was not checked for any rule: no deployed bytecode was compared with these commits. Role holders were read only where stated.

---

## 2. Rule by rule

Each rule is described under the five questions of the brief:
1. where it is enforced;
2. which direction it limits;
3. what happens at the limit;
4. how it accounts for flows;
5. who controls it.

### 2.1 Wormhole Governor (Guardian software)

**Repository:** wormhole @ `bb5957f`. File paths are relative to `node/pkg/`, except those beginning with `node/`.

1. **Where.** Off-chain, in each Guardian node, before the Guardian signs.
   - Messages are keyed to the emitter (source) chain of a token-bridge transfer.
   - `processor/observation.go` L233: `if !p.governor.ProcessMsg(k) {`. The message is not signed now.
   - The rule is opt-in per node. `node/cmd/guardiand/node.go` L566: `Bool("chainGovernorEnabled", false, "Run the chain governor")`.
   - The rule binds only if enough Guardians run it to deny a 13-of-19 quorum.
2. **Direction.** Outbound value emitted by each governed chain's token bridge, summed across destinations and across listed tokens. Unlisted tokens pass. `governor/governor.go` L780: `// If we don't care about this token, the VAA can be published.`
3. **At the limit: queue.**
   - Large transfers and transfers that do not fit are enqueued with a 24 h release time. `governor.go` L53–54: `maxEnqueuedTime = time.Hour * 24`; L597 `if emitterChainEntry.isBigTransfer(scaledValue) {`, L599 `releaseTime = now.Add(maxEnqueuedTime)`; L610 `} else if newScaledTotalValue > emitterChainEntry.dailyLimit*guardianDB.ScaledValueFactor {`, L612 the same release time.
   - **Automatic release at the deadline, not counted against the limit.** L858 `countsTowardsTransfers := true`; for big transfers L860 `if now.Before(pe.dbData.ReleaseTime) {` … L864 `countsTowardsTransfers = false`; for small transfers L872–873 `} else if now.After(pe.dbData.ReleaseTime) { countsTowardsTransfers = false`. A queued small transfer that fits before its deadline is released and counted (L888, L918).
   - **Manual release, not counted.** `governor/governor_monitoring.go` L190: `// Admin command to remove a VAA from the pending list and publish it without regard to (or impact on) the daily limit.` Each Guardian acts locally, so a release takes effect once 13 of 19 sign.
   - **Cancel.** `DropPendingVAA` (L160) deletes the message from the local queue. If 7 of 19 drop it, the message cannot reach quorum.
   - **Extend.** `resetReleaseTimerForTime` sets `pe.dbData.ReleaseTime = now.Add(time.Duration(numDays) * time.Hour * 24)` (L239). `adminrpc/adminserver.go` L46 `const maxResetReleaseTimerDays = 90`, enforced at L1328. The whitepaper text says 30 days.
4. **Accounting.**
   - **Window.** Sliding 24 h window on Guardian-local timestamps: L303 `gov.dayLengthInMinutes = 24 * 60`; L559 `startTime := now.Add(-time.Minute * time.Duration(gov.dayLengthInMinutes))`; L1144 "`Timestamp` is created by the Governor; it is not read from the actual on-chain transaction".
   - **Unit and price.** USD notional at max(hard-coded floor, CoinGecko). `governor_prices.go` L310: `if (te.coinGeckoPrice == nil) || (te.coinGeckoPrice.Cmp(te.cfgPrice) < 0) {` → floor price.
   - **Scope.** Aggregated over listed tokens per emitter chain.
   - **Gross by default. Net if the Guardian sets `--governorFlowCancelEnabled`** (`node/cmd/guardiand/node.go` L567, default false).
     - What counts: an inbound transfer to the governed chain, entered as a negative entry (L1092: `destinationChainEntry.addFlowCancelTransfer(transfer.inverse())`).
     - Token allow-list: USDC, USDT and DAI variants (`flow_cancel_tokens.go` L11–23).
     - Corridor allow-list: `{first: vaa.ChainIDEthereum, second: vaa.ChainIDSui}` only (`flow_cancel_corridors.go` L12–15).
     - **Cost of a counted inflow.** A token-bridge transfer message emitted on the corridor partner and published by this Guardian. It is added when the Guardian publishes the message (L693–694; L956–962, inside `if countsTowardsTransfers {` L918), not when the message is redeemed. On the partner chain that message requires a real lock or burn of the same stablecoin unless the partner chain's contract is faulty. Big transfers and timer-released transfers never count as offsets.
     - Banking: L1131 `// Return 0 even if the sum is negative.` Negative entries stay in the 24 h list, so an inflow surplus raises the outflow allowance within the window.
5. **Control.**
   - Limits are compiled into the node software. `governor/mainnet_chains.go` L13–14: `{EmitterChainID: vaa.ChainIDSolana, DailyLimit: 20_000_000, BigTransactionSize: 1_000_000}`, `{EmitterChainID: vaa.ChainIDEthereum, DailyLimit: 10_000_000, BigTransactionSize: 1_000_000}`. Changes ship as node releases.
   - Each Guardian enables or disables the rule, and releases, drops or extends queued messages through its admin RPC. **The controlling parties are the verifier set.** A quorum that signs without the Governor is not constrained by it.
   - Adjacent rule, the **Notary** (`notary/notary.go`).
     - Messages that the transfer verifier marks anomalous get verdict `Delay`: L83 `DefaultDelay = time.Hour * 24 * 4`. The admin can extend the hold to `MaxDelayDays = 30` (L84; `notary/admincommands.go` L97–122).
     - When the hold expires, the message is passed to the Governor and then the Accountant automatically: `processor/processor.go` L632 "Notary -> Governor -> Accountant", L636 `readyMsgs := p.notary.ReleaseReadyMessages()`.
     - Rejected messages get `Blackhole` and are never signed.
     - This hold is not tied to amounts.

### 2.2 Wormhole Global Accountant (Guardian software plus a Wormchain contract)

**Repository:** wormhole @ `bb5957f`.

1. **Where.** At the verifier.
   - Each Guardian submits its observation to the accountant contract on Wormchain. With enforcement on, it publishes only after the contract commits. `node/pkg/accountant/accountant.go` L370–371: `// If we are not enforcing accountant, the event can be published. Otherwise we have to wait to hear back from the contract.` / `return !enforceFlag, nil`.
   - Opt-in flag: `node/cmd/guardiand/node.go` L414 `Bool("accountantCheckEnabled", false, "Should accountant be enforced on transfers")`.
   - The contract commits a transfer once a quorum of Guardian observations arrives: `cosmwasm/contracts/global-accountant/src/contract.rs` L209 `if data.num_signatures() < quorum {` returns Pending.
2. **Direction.** Both. There is one account per (chain, token origin). `cosmwasm/packages/accountant/src/state/account.rs` L18–36:
   - `lock_or_burn` adds to a native account and subtracts from a wrapped account;
   - `unlock_or_mint` subtracts from a native account and adds to a wrapped account.
3. **At the limit.** The transfer is rejected and dropped. There is no queue and no release.
   - `packages/accountant/src/contract.rs` L184–185 `src.lock_or_burn(t.data.amount).context(TransferError::InsufficientSourceBalance)?;` and L192 `dst.unlock_or_mint(…)` with `InsufficientDestinationBalance`.
   - `node/pkg/accountant/submit_obs.go` L294: `"insufficient balance error detected, dropping transfer"`.
4. **Accounting.** A conservation ledger in token units, with no time window. A release on a native chain needs a recorded balance there, which only quorum-observed locks create. The rule therefore bounds releases by recorded deposits.
5. **Control.** Guardians: the per-node enforce flag, plus a governance VAA `ModifyBalance` (`global-accountant/src/contract.rs` L410) that needs a Guardian quorum. **Same parties as the verifier set.** The ledger holds against a faulty chain contract or a faulty minority. A quorum can submit any observations it likes.

### 2.3 Wormhole Native Token Transfers (NTT)

**Repository:** native-token-transfers @ `9fa9136`. EVM files are under `evm/src/`.

1. **Where.** On-chain in the integrator's `NttManager`:
   - an outbound bucket at the source send;
   - one inbound bucket per source chain at the destination release.
   - Inbound messages are released once enough transceivers attest: `NttManager/ManagerBase.sol` L296–297 `return messageAttestations(digest) >= threshold && threshold > 0;`.
2. **Direction.** Both.
3. **At the limit.**
   - **Outbound.** The sender chooses: revert (`NttManager/NttManager.sol` L499 `revert NotEnoughCapacity(getCurrentOutboundCapacity(), amount);`) or queue.
   - **Inbound.** Always queued. L302 `_enqueueInboundTransfer(digest, nativeTransferAmount, transferRecipient);`.
   - **Automatic release after `rateLimitDuration`, not counted against the limit.**
     - Anyone can call the release functions; they carry no access check.
     - Inbound: L317 `function completeInboundQueuedTransfer(`, L327 `if (block.timestamp - queuedTransfer.txTimestamp < rateLimitDuration) {` reverts while still queued, then L335 `_mintOrUnlockToRecipient(digest, queuedTransfer.recipient, queuedTransfer.amount, false);`. The amount is not consumed against the inbound bucket.
     - Outbound: L349, then L356 `// run it through the transfer logic and skip the rate limit`.
   - **Cancel.** Only for outbound items, and only by the sender (L379 `if (queuedTransfer.sender != msg.sender) {`). There is no function that cancels an inbound queued item. Stopping it takes `pause()` (owner or pauser, `ManagerBase.sol` L338) or an upgrade (owner).
   - Solana program: `solana/programs/example-native-token-transfers/src/queue/rate_limit.rs` L40 `pub const RATE_LIMIT_DURATION: i64 = 60 * 60 * 24; // 24 hours`, L102 `RateLimitResult::Delayed(now + Self::RATE_LIMIT_DURATION)`.
4. **Accounting.**
   - **Bucket.** Token bucket in token units (trimmed). `libraries/RateLimiter.sol` L188–189: `uint256 calculatedCapacity = rateLimitParams.currentCapacity.getAmount() + (rateLimitParams.limit.getAmount() * timePassed) / rateLimitDuration;`, capped at `limit`. The duration is immutable (L15). A duration of 0 disables limits.
   - **Scope.** Per token (one manager per token per chain); inbound per source chain.
   - **Net ("backflow").** Each direction refills the other.
     - A received transfer refills the outbound bucket (L312 `_backfillOutboundAmount(nativeTransferAmount);`).
     - A sent transfer refills the inbound bucket for its destination chain (L532 `_backfillInboundAmount(internalAmount, recipientChain);`).
     - **Cost of a counted inflow** for the release-side (inbound) bucket on chain A: an outbound send from A to the same chain, which needs a real burn or lock of the same token on A. For the outbound bucket, the offset is an attested inbound message.
     - Refills saturate at the limit (`RateLimiter.sol` L286 `…saturatingAdd(amount).min(rateLimitParams.limit)`). No banking beyond a full bucket.
5. **Control.** The integrator's owner sets limits (`setOutboundLimit`, `setInboundLimit`, L137–150, `onlyOwner`), the transceiver set and threshold, upgrades, and unpause. Owner or pauser can pause. **The owner is not the attesting set, although the owner chooses it.**

### 2.4 Chainlink CCIP token-pool rate limiters

**Repositories:** chainlink-ccip main @ `055a7e7` (pools v2.0) and @ `bccdd15` (v1.6).

1. **Where.** On-chain in the token pool, at both ends:
   - outbound bucket in `lockOrBurn` at the source send: `chains/evm/contracts/pools/TokenPool.sol` L435 `_consumeOutboundRateLimit(lockOrBurnIn.localToken, lockOrBurnIn.remoteChainSelector, amount);`;
   - inbound bucket in `releaseOrMint` at the destination release: L489 `_consumeInboundRateLimit(…)`.
   - v2.0 adds separate fast-finality buckets (L433, L487) that fall back to the default bucket when disabled (L810–811).
2. **Direction.** Both, per remote chain.
3. **At the limit: revert.**
   - `libraries/RateLimiter.sol` L60–61 `if (capacity < requestTokens) { revert TokenMaxCapacityExceeded(…)`; L63–74 `if (tokens < requestTokens) { … revert TokenRateLimitReached(minWaitInSeconds, tokens, tokenAddress);`.
   - At the destination, the message enters state FAILURE and stays retryable with no deadline.
     - v2.0 `offRamp/OffRamp.sol` L182: execution "is completely permissionless". L234–237: retry allowed from `UNTOUCHED` or `FAILURE`.
     - v1.6 `OffRamp.sol` L423–428: manual execution is allowed after a failure or once the commit report is old.
   - A retry consumes the inbound bucket again. Nothing is released automatically.
4. **Accounting.**
   - **Bucket.** Token bucket in local token units, per pool × remote chain × direction (× finality class). `RateLimiter.sol` L131 `return _min(capacity, tokens + timeDiff * rate);`.
   - **Gross.** No path adds capacity from opposite flows.
   - **Effect of a parameter change** (the versions differ):
     - v2.0 refills to full (L112–116 `s_bucket.tokens = config.capacity;`);
     - v1.6 keeps the current level (`RateLimiter.sol` L101 `s_bucket.tokens = uint128(_min(config.capacity, s_bucket.tokens));`).
   - No lane-level aggregate USD limiter exists in either commit. The deploy note found one only in the v1.2 documentation.
5. **Control.**
   - `setRateLimitConfig` → `_onlyOwnerOrRateLimitAdmin()` (TokenPool L875, L939–942 `if (msg.sender != s_rateLimitAdmin && msg.sender != owner()) {`). The pool owner is the token administrator.
   - The RMN can block a remote chain. Both `lockOrBurn` and `releaseOrMint` revert with `CursedByRMN` (L422, L479).
   - **Not the verifier set.** Pool owner ≠ the committing and executing DON. The RMN is a separate committee.

### 2.5 LayerZero OApp `RateLimiter`

**Repository:** devtools @ `4973ba8`, `packages/oapp-evm/contracts/oapp/utils/RateLimiter.sol`.

1. **Where.** An abstract contract: the integrator calls `_outflow` where it chooses, usually on send at the source. The pinned devtools and LayerZero-v2 commits contain no call sites.
2. **Direction.** Per destination endpoint, outbound. Inbound appears only through the optional `_inflow`.
3. **At the limit: revert.**
   - L245 `if (_amount > amountCanBeSent) revert RateLimitExceeded();`.
   - L236: `// @dev By default dstEid that have not been explicitly set will return amountCanBeSent == 0.`
4. **Accounting.**
   - **Form.** A token bucket written as in-flight amount with linear decay. L222 `uint256 decay = (_limit * timeSinceLastDeposit) / (_window > 0 ? _window : 1);`, L225 `amountCanBeSent = _limit <= currentAmountInFlight ? 0 : _limit - currentAmountInFlight;`. Token units, per endpoint.
   - **Optional net.** L254 "If you move 150 out, and 100 in, you effective inflight should be 50", L261 `rl.amountInFlight = uint192(_amount >= rl.amountInFlight ? 0 : rl.amountInFlight - _amount);`.
   - Whether an inflow counts is the integrator's choice.
5. **Control.**
   - The inheriting contract exposes `_setRateLimits` (L175) and `_resetRateLimits` (L195, which sets in-flight to 0), normally to the OApp owner.
   - The OApp owner or delegate also selects the DVNs and holds endpoint powers:
     - `EndpointV2.sol` L353–356: the caller must be the OApp or its delegate;
     - `MessagingChannel.sol` L95 `nilify` blocks execution of a verified message until it is re-verified; L112 `burn` deletes it.
   - **Not the verifier set.**

### 2.6 LayerZero Stablecoin, RWA and multi-asset OFT modules (npm 1.2.83)

**Files:** `utils-upgradeable-evm-contracts/contracts/rate-limiter/RateLimiterBaseUpgradeable.sol` (RLB) and `oft-upgradeable-evm-contracts/contracts/extended/*.sol`.

1. **Where.** On-chain in the OFT, at both ends.
   - `OFTBurnMintExtendedRBACUpgradeable.sol` L97–106: `_debit(…) internal virtual override whenNotPaused(_dstEid)` … `_outflow(_dstEid, _from, amountReceivedLD);` (source send).
   - L116–122: `_credit(…)` … `_inflow(_srcEid, _to, _amountLD);` (destination release).
   - The lock/unlock and native variants have the same structure.
2. **Direction.** Both, with outbound and inbound usage per ID, or one global state (`useGlobalStateFlag`, RLB L124).
3. **At the limit: revert.**
   - RLB L338–341: `if (forwardAvailableAmount < amount) { revert RateLimitExceeded(forwardAvailableAmount, amount);`.
   - An inbound revert reverts `lzReceive`. The endpoint clears the payload before execution (`EndpointV2.sol` L180–181), so the revert undoes the clearing, the message stays verified, and anyone can retry (`lzReceive` has no caller check, L172–178).
   - There is no queue and no deadline. A retry consumes again.
4. **Accounting.**
   - **Form.** Token bucket with linear decay (RLB L492 `uint256 decay = (_limit * timeSinceLastUpdate) / (_window > 0 ? _window : 1);`). Token units (optionally downscaled); per destination or global.
   - **Optional net** (`netAccountingEnabled`). RLB L348–349: `if (backwardEnabled && netAccountingEnabled) { backwardUsage = Math.saturatingSub(backwardUsage, amount);`.
     - **Cost of a counted inflow** for the inbound (release) usage on chain A: an outbound `_debit` on A, which needs a real burn or lock of the same token.
     - Saturates at zero usage, so there is no banking beyond a full bucket.
   - **Exemptions.** Addresses can be exempted (RLB L314 `(addressExemptionEnabled && isRateLimitAddressExempt(_user))` returns early).
5. **Control.**
   - `RATE_LIMITER_MANAGER_ROLE` sets configs, exemptions and usage states. `RateLimiterRBACUpgradeable.sol` L27, L50–86. `setRateLimitStates` overwrites usage, RLB L573–590.
   - **Pause by ID covers sends only.** `whenNotPaused(_dstEid)` sits on `_debit`. `_credit` has no pause modifier in the burn/mint, lock/unlock or native variants. Inbound can be stopped through rate-limit configs or endpoint `nilify`/`burn`.
   - **Not the verifier set.**

### 2.7 Axelar ITS flow limits

**Repository:** interchain-token-service @ `0f4b037`.

1. **Where.** On-chain in each chain's `TokenManager`, at both ends.
   - `contracts/TokenHandler.sol` L39 `ITokenManager(tokenManager).addFlowIn(amount);` in `giveToken` (destination release or mint).
   - L88 `addFlowOut(amount)` in `takeToken` (source burn or lock).
   - The message must be approved by the gateway: `contracts/InterchainTokenService.sol` L450 `if (!gateway.validateContractCall(commandId, sourceChain, sourceAddress, payloadHash)) revert NotApprovedByGateway();`.
2. **Direction.** Both, as net flow within an epoch.
3. **At the limit: revert.**
   - `contracts/utils/FlowLimit.sol` L115 `if (flowAmount > flowLimit_) {` reverts with `FlowAmountExceededLimit`; L124–127 `uint256 netFlow = newFlow >= reverseFlow ? newFlow - reverseFlow : reverseFlow - newFlow;` … `if (netFlow > flowLimit_) { revert FlowLimitExceeded(…)`.
   - An inbound revert reverts `execute`, so the gateway approval is restored and the call can be retried later. There is no queue.
   - The express path: an express executor pays the recipient from its own funds. The flow-in is counted when the approved message later repays the executor (ITS L715–718).
4. **Accounting.**
   - **Window.** Fixed calendar epochs: L18 `uint256 private constant EPOCH_TIME = 6 hours;`, with `epoch = block.timestamp / epochTime()` (L143, L158).
   - **Scope.** Token units, per token manager (one token on one chain).
   - **Net.** The rule caps |in − out| within the epoch, and a single transfer cannot exceed L.
     - **Cost of a counted inflow** for releases (flow-in) on chain A: flow-out on A in the same epoch, which is a real burn or lock of the same token on A.
     - Surplus banks within the epoch: deposits of X allow releases up to X + L.
   - **Off switch.** `flowLimit_ == 0` disables the rule (L141, L156).
   - **ITS Hub supply tracking** (axelar-amplifier @ `6703b92`), a verifier-level check:
     - `contracts/interchain-token-service/src/state.rs` L77–80 `Tracked(Uint256)`: "ITS Hub will not allow bridging back more than this amount of the token from the corresponding chain";
     - `contract/execute/interceptors.rs` L13–26 `checked_sub` fails with `TokenSupplyInvariantViolated`;
     - it applies only to `TokenDeploymentType::Trustless` (state.rs L131–134; otherwise `Untracked`);
     - its call sites are not in the sparse checkout.
5. **Control.**
   - The token's `FLOW_LIMITER` role sets the limit (`token-manager/TokenManager.sol` L167). The role is held by the token operator and by ITS (L112–114).
   - The ITS operator sets limits in bulk (ITS L617, `onlyRole(uint8(Roles.OPERATOR))`). This works only while ITS keeps the token's `FLOW_LIMITER` role, which the token operator may remove (TokenManager L113).
   - The ITS operator or owner pauses (`setPauseStatus`, L647).
   - **Partly the verifier set.** The token operator is the issuer. The ITS operator and owner are Axelar-side roles.

### 2.8 Axelar legacy gateway mint limit (axl-tokens)

**Repository:** axelar-cgp-solidity @ `43ec407`, `contracts/AxelarGateway.sol`.

1. **Where.** On-chain at the destination release or mint. `_mintToken` L744 `_setTokenMintAmount(symbol, tokenMintAmount(symbol) + amount);` runs for both external (lock) and internal (mint) tokens.
2. **Direction.** Inbound to the gateway's chain.
3. **At the limit: revert, retryable.**
   - L865 `if (limit > 0 && amount > limit) revert ExceedMintLimit(symbol);`.
   - The batch loop marks a failed command as not executed: L564 `_setCommandExecuted(commandId, true);` … L571 `else _setCommandExecuted(commandId, false);`. The same signed command can be resubmitted.
4. **Accounting.**
   - Fixed 6 h epochs: L867 `_setUint(_getTokenMintAmountKey(symbol, block.timestamp / 6 hours), amount);`.
   - Gross, per symbol, token units. A limit of 0 means no cap. The deploy note read 0 for USDC and WETH on Ethereum.
   - Network-level rule (historical): axelar-core v1.2.0 `x/nexus/keeper/rate_limit.go` had a per-chain, per-asset, per-direction cap over fixed windows (`RateLimitTransfer`, L18–49). There is no `rate_limit.go` in `x/nexus/keeper` at main `aaa8a4e`. Whether the rule was removed or moved was not established.
5. **Control.** `onlyMintLimiter`: the mint-limiter or governance address (L122–126). Governance executes proposals relayed through the same gateway. **Partly the verifier set.**

### 2.9 Hyperlane `RateLimitedHook` and `RateLimitedIsm`, plus newer variants at HEAD

**Repository:** hyperlane-monorepo @ `e3eee02`. File paths are relative to `solidity/contracts/`.

1. **Where.**
   - **Hook:** source send, after dispatch (`hooks/warp-route/RateLimitedHook.sol` L80–87 `_postDispatch` → `_validateAndConsumeFilledLevel(newAmount);`).
   - **ISM:** destination release (`isms/warp-route/RateLimitedIsm.sol` L53–65 `verify` → `_validateAndConsumeFilledLevel(newAmount);`).
   - The ISM's module type is NULL (L45–46), so it must be combined with an authenticating module.
2. **Direction.** Hook outbound; ISM inbound.
3. **At the limit: revert.**
   - `libs/RateLimited.sol` L187 `require(_consumedAmount <= adjustedFilledLevel, "RateLimitExceeded");`.
   - `Mailbox.sol` records the delivery (L225) before calling the ISM (L236 `ism.verify(_metadata, _message)`). A revert undoes the record, and the message can be processed again later by anyone.
4. **Accounting.**
   - Token bucket, starting full. L66 `return refillRate * DURATION;`, L164 `uint256 _newRefillRate = _capacity / DURATION;`. `DURATION` is immutable and set at construction (L44–46).
   - Gross, token units, per hook or ISM instance (one route).
5. **Control.** `setRefillRate` is `onlyOwner` (L162), held by the route owner, who also chooses the validators. **Not the verifier set.**

**Variants at HEAD** (deployment not checked):

- **`NetFlowRateLimitedHookIsm`** (`hooks/warp-route/NetFlowRateLimitedHookIsm.sol`).
  - One contract serves as both hook and ISM. L16 "caps a warp router's net collateral outflow"; L22 "*net* amount leaving the router is rate limited".
  - On a collateral route, delivery consumes (L166–167) and dispatch credits (L195–197).
  - Capacity is a share of live TVL (`libs/TvlRateLimited.sol` L157 `return (localCollateral() * thresholdBps) / BPS_DENOMINATOR;`), net of LP-reclaimable assets (L149).
  - **Geometric, net.** A counted inflow is a real deposit of the same token into the router. The library notes (L40) that "raising the balance to lift the cap also funds the pool the cap gates".
- **`DelayedFlowRouterHookIsm`** (`isms/warp-route/DelayedFlowRouterHookIsm.sol`).
  - Over-limit messages are delayed rather than rejected. L177–178: `uint256 deficitSecs = _consume(_toLocalAmount(messageAmount)); uint48 wait = deficitSecs > maxDelay ? maxDelay : uint48(deficitSecs);`.
  - Overage accumulates as debt (L207 `debt += _overage;`), so splitting a transfer does not shorten the wait.
  - Origin deposits credit the bucket 1:1 (L134). Capacity is TVL-proportional.
  - Release is automatic once `readyAt` passes (`isms/routing/TimelockRouter.sol` L194–195). **This makes a cliff at `maxDelay`.** The contract notes (L43–44) recommend composing it with `PausableIsm`, so that monitors can stop delivery during the delay window.
  - The wait is set by a separate preverification message carrying (id, amount). The rule's metering is therefore only as independent as the module that verifies that message.

### 2.10 Circle CCTP per-message cap

**Repositories:** evm-cctp-contracts @ `a92a2b4`; stablecoin-evm @ `fc85788`.

1. **Where.**
   - **Source send, burn only.** `src/TokenMinter.sol` L116 `onlyWithinBurnLimit(burnToken, burnAmount)`. `src/roles/TokenController.sol` L100 `require(_allowedBurnAmount > 0, "Burn token not supported");`, L103 `"Burn amount exceeds per tx limit"`.
   - **The destination mint has no amount check in CCTP.** TokenController L180–182: "Burns with amounts exceeding `burnLimitPerMessage` will revert. Mints do not respect this value, so if this limit is reduced, previously burned tokens will still be mintable." `TokenMinter.mint` (L85–102) and `v2/TokenMinterV2.mint` (L54–83) mint after the attestation check (`MessageTransmitter.sol` L255 `_verifyAttestationSignatures(message, attestation);`).
   - **Token level.** USDC's `mint` enforces a cumulative minter allowance. `contracts/v1/FiatTokenV1.sol` L133–141: `uint256 mintingAllowedAmount = minterAllowed[msg.sender]; require(_amount <= mintingAllowedAmount, "FiatToken: mint amount exceeds minterAllowance"); … minterAllowed[msg.sender] = mintingAllowedAmount.sub(_amount);`.
     - Burns do not restore the allowance (L363–378). Only the master minter resets it (`configureMinter`, L329–336).
     - On Ethereum the allowance read this pass: V1 108.19M and V2 1,168.70M USDC.
2. **Direction.** Outbound burns (cap). Inbound mints face only the token-level allowance.
3. **At the limit.** The burn reverts at the source. A mint beyond the allowance reverts at the destination until the master minter raises the allowance. There is no queue.
4. **Accounting.**
   - Per message, per token, with no window.
   - The allowance is cumulative and gross.
   - The Fast Transfer Allowance is off-chain (attestation service); not in this code.
5. **Control.** Circle holds tokenController, attester manager (`signatureThreshold`, `roles/Attestable.sol` L61), pauser (`roles/Pausable.sol` L64), and USDC master minter. **The same organization runs the attestation.**

### 2.11 Linea message-service limit

**Repository:** linea-monorepo @ `7952d16`.

1. **Where.**
   - **Destination release on L1.** In the claim (`contracts/src/messaging/l1/L1MessageService.sol` L115 `_setL2L1MessageToClaimed(_params.messageNumber);` L117 `_addUsedAmount(_params.fee + _params.value);`; also L179). The claim runs after the L2 Merkle root is finalized on L1.
   - **Source send on L2.** `l2/v1/L2MessageServiceV1.sol` L104–105 `/// @dev Rate limit and revert is in the rate limiter.` `_addUsedAmount(valueSent + postmanFee);`.
2. **Direction.** L2 → L1 only.
3. **At the limit: revert.**
   - `contracts/src/…/limiting/RateLimiter.sol` (the repository's only `RateLimiter.sol`) L68–70 `if (_usedAmount > limitInWei) { revert RateLimitExceeded(); }`.
   - The claim is permissionless and can be retried in a later period. There is no queue.
4. **Accounting.**
   - **ETH value plus fees only.** ERC-20 transfers through the token bridge pass only `msg.value` to the message service (`bridging/token/TokenBridgeBase.sol` L260, L413 `messageService.sendMessage{ value: msg.value }(`). Token amounts are not metered.
   - **Gross. The window is anchored at first use after expiry, not at calendar boundaries:**

     ```
     if (currentPeriodEnd < block.timestamp) {
         currentPeriodEnd = block.timestamp + periodInSeconds;
     } else {
         _usedAmount += currentPeriodAmountInWei;
     }
     ```

     (L62–66)
5. **Control.**
   - `RATE_LIMIT_SETTER_ROLE` changes the limit (L84). Within the period, the change can only lower usage.
   - `USED_RATE_LIMIT_RESETTER_ROLE` zeroes usage (L113–117).
   - The claim checks `_requireTypeAndGeneralNotPaused(PauseType.L2_L1);` (L103).
   - Messages are proof-verified, and role holders were not read here. **Not the verifier set** in the sense used above.

### 2.12 StarkGate withdrawal limit

**Repository:** starkgate-contracts @ `07e11c3`.

1. **Where.**
   - **Destination release on L1.** `src/solidity/StarknetTokenBridge.sol` L490–507 `withdraw` consumes the L2→L1 message, then (L502–505) `if (tokenSettings()[token].withdrawalLimitApplied) { WithdrawalLimit.consumeWithdrawQuota(token, amount); }`, then transfers.
   - **Source send on L2.** `packages/bridge/src/token_bridge.cairo` L409–411 in `initiate_token_withdraw`.
2. **Direction.** L2 → L1 withdrawals.
3. **At the limit: revert.**
   - `src/solidity/WithdrawalLimit.sol` L85 `require(intradayAllowance >= amount, "EXCEEDS_GLOBAL_WITHDRAW_LIMIT");`.
   - L1 `withdraw` is permissionless. The message stays unconsumed and can be withdrawn on a later day. There is no queue.
4. **Accounting.**
   - **Calendar UTC day** (L26 `uint256 day = block.timestamp / 86400;`), per token.
   - **Allowance = percentage of the bridge's balance at the first withdrawal of the day** (L34–44: `currentBalance = IERC20(token).balanceOf(address(this));` … `return (currentBalance * withdrawLimitPct) / 100;`; L72–77 computes it only while the day's quota is uninitialized). The default is 5% (L12).
   - **Geometric across days. Gross within a day.** Deposits made after the day's first withdrawal do not raise that day's quota. They do raise the next day's base by 5% of the deposit.
   - **L2.** The default is 5% of L2 total supply (`token_bridge.cairo` L46, L616–620); the forum post says 8%.
   - **L2 locked-amount check** (L413–425). When monitoring is enabled, a withdrawal cannot exceed the recorded L1 deposits less prior withdrawals (`assert(locked_amount >= amount, …)`); deposits add to it (L580–590). This is a conservation check like the Wormhole accountant's.
5. **Control.**
   - `enableWithdrawalLimit(address token)` is restricted to the agent role (L349). `disableWithdrawalLimit` is restricted to the admin role (L357), which the 2025-08-26 forum post assigns to a council multisig. The Cairo equivalents are L311–324.
   - **On 2026-10-16 the L1 limit was not applied for ETH or STRK** (on-chain read, §1).
   - Messages are proof-verified. **Not the verifier set.**

### 2.13 Ronin withdrawal limitation

**Repository:** ronin-bridge-contracts @ `b037428`.

1. **Where.** Destination release on Ethereum (`src/mainchain/MainchainGatewayV3.sol` `_submitWithdrawal`). Operator signatures are checked against weights from the BridgeManager (L456–457).
2. **Direction.** Ronin → Ethereum.
3. **At the limit.**
   - **Below `lockedThreshold`: revert** if the day's total would reach the cap. L284–285 `… !_reachedWithdrawalLimit(_tokenAddr, _quantity))) { revert ErrReachedDailyWithdrawalLimit();`. `extensions/WithdrawalLimitation.sol` L297–302 uses `<=`, so reaching the cap exactly also reverts.
   - **At or above `lockedThreshold`:**
     - the withdrawal also needs high-tier vote weight whenever `lockedThreshold` ≥ `highTierThreshold`, as in the deployed values (L387–390);
     - it is **held** (L322–323 `if (_locked) { withdrawalLocked[_id] = true;`);
     - it is **exempt from and not counted in** the daily cap (WithdrawalLimitation L293–295; `_recordWithdrawal` at L328 runs only on the unlocked path);
     - it is released only by `unlockWithdrawal` (L150, `onlyRole(WITHDRAWAL_UNLOCKER_ROLE)`), which pays the unlock fee to the caller (L168).
   - **There is no deadline and no automatic release.**
4. **Accounting.** Calendar UTC day (L297, L309 `block.timestamp / 1 days`). Gross, per token, token units.
5. **Control.**
   - The proxy admin sets thresholds and caps (`onlyAdmin`, `extensions/WithdrawalLimitation.sol` L109–160).
   - Admin or `emergencyPauser` pauses (`extensions/GatewayV3.sol` L113).
   - Unlockers are set at initialization (L97).
   - In the BridgeManager each operator is registered with a paired governor key and the same weight (`extensions/bridge-operator-governance/BridgeManager.sol` L97–103, L135–137). That this contract is the gateway's proxy admin was not read on-chain. **Partly the verifier set.**

### 2.14 Celer cBridge volume control and delayed transfers

**Repository:** sgn-v2-contracts @ `dd60f95`.

1. **Where.** Destination release. In `contracts/liquidity-bridge/Bridge.sol` `relay`, signatures come first (L132 `verifySigs(…)`), then L148 `_updateVolume(request.token, request.amount);`. The same pattern appears in `Pool.sol` L103, `OriginalTokenVault(V2)`, and `PeggedTokenBridge(V2)`. Source-side min and max send are separate.
2. **Direction.** Inbound releases on each chain.
3. **At the limit.**
   - **Epoch cap: revert** (`contracts/safeguard/VolumeControl.sol` L45 `require(volume <= cap, "volume exceeds cap");`). The signed relay can be resubmitted later.
   - **Above `delayThresholds[token]`: fixed delay.** Bridge.sol L150 `if (delayThreshold > 0 && request.amount > delayThreshold) {` → `_addDelayedTransfer`.
   - **Automatic release.** `executeDelayedTransfer` is permissionless apart from `whenNotPaused` (`Pool.sol` L113). `safeguard/DelayedTransfer.sol` L57 `require(block.timestamp > transfer.timestamp + delayPeriod, "delayed transfer still locked");` reads the *current* `delayPeriod`, so a governor change applies to items already queued.
   - **Delayed items are counted against the epoch volume when queued** (`_updateVolume` precedes the delay branch). Release does not count again.
   - There is no cancel function.
4. **Accounting.** Fixed epochs (`VolumeControl.sol` L39 `uint256 epochStartTime = (timestamp / epochLength) * epochLength;`). Gross, per token, token units.
5. **Control.**
   - Governors set caps, epoch and delay (`onlyGovernor`). Pausers pause.
   - Optional `Sentinel` (`safeguard/sentinel/`): without guard consent, governors may only tighten (`GuardedGovernor.sol` L84 "not in relax mode, can only increase period", L124 "… can only reduce cap"), and unpausing requires relaxed mode (`GuardedPauser.sol` L56, L62). Relaxed mode needs `numRelaxedGuards >= relaxThreshold` (`Guard.sol` L104).
   - Whether the deployed bridges' roles sit behind the Sentinel was not checked.
   - **Not the verifier set** (SGN signatures).

### 2.15 Gnosis OmniBridge and xDai bridge daily limits

**Repositories:** omnibridge @ `ccd9003`; tokenbridge-contracts @ `4787340`.

1. **Where.** Both ends.
   - Source: `contracts/upgradeable_contracts/ForeignOmnibridge.sol` L145–146 `require(withinLimit(_token, _value)); addTotalSpentPerDay(…)`.
   - Destination: L114–115 `require(withinExecutionLimit(_token, _value)); addTotalExecutedPerDay(…)`. The home side has the same lines (`HomeOmnibridge.sol` L128, L167).
2. **Direction.** Both, with separate daily and per-transaction limits for each.
3. **At the limit.** The three cases differ.
   - **OmniBridge destination: the message fails and is consumed.** The AMB marks it relayed before execution (`arbitrary_message/BasicForeignAMB.sol` L122 `setRelayedMessages(msgId, true);`) and records a failed call (`MessageProcessor.sol` L191–197).
     - Anyone may then call `requestFailedMessageFix` (`components/common/FailedMessagesProcessor.sol` L18–27). This sends a return message that refunds the sender on the origin chain (`fixFailedMessage`, L34–43).
     - There is no queue and no waiting for the reset.
   - **xDai bridge, Ethereum side: revert, retryable** (`BasicForeignBridge.sol` L30–38; `erc20_to_native/ForeignBridgeErcToNative.sol` L60–62 `function onFailedMessage(…) internal { revert(); }`).
   - **xDai bridge, Gnosis side: held** as "above limits" (`HomeBridgeErcToNative.sol` L220–225). Only the upgradeability owner can refund or re-release (`HomeOverdrawManagement.sol` L23–26, `onlyIfUpgradeabilityOwner`).
4. **Accounting.**
   - Calendar UTC day (`components/common/TokensBridgeLimits.sol` L134–137 `return block.timestamp / 1 days;`).
   - Gross, per token (OmniBridge) or single asset (xDai), token units.
   - `withinExecutionLimit` (L122–127) also caps each transaction.
5. **Control.** The owner sets limits (`onlyOwner`, L145, L158). Validators sign messages; the AMB optionally also requires Hashi approval (`BasicForeignAMB.sol` L121). **Not the verifier set** (owner multisig ≠ validator keys; overlap not checked).

### 2.16 BNB Chain BEP-171 time lock

**Repository:** bsc-genesis-contract @ tag v1.1.9 `d647bfe`; master `8464181` for the current state.

1. **Where.** Destination release on BSC, at credit of a Beacon Chain → BSC transfer (`contracts/TokenHub.sol` v1.1.9 L272, L295 `if (!_checkAndLockTransferIn(transInSynPkg)) {`).
2. **Direction.** BC → BSC.
3. **At the limit: fixed delay, automatic release.**
   - L356–365:

     ```
     uint256 _limit = largeTransferLimitMap[transInSynPkg.contractAddr];
     if (_limit == 0 || transInSynPkg.amount < _limit) {
         return false;
     }
     …
     lockInfo.amount = lockInfo.amount.add(transInSynPkg.amount);
     lockInfo.unlockAt = block.timestamp + lockPeriod;
     ```

     A new large transfer to the same (token, recipient) restarts the lock for the whole accumulated amount.
   - Release: anyone calls `withdrawUnlockedToken` after `unlockAt` (L317–321 `require(block.timestamp >= lockInfo.unlockAt, "still on locking period");`).
   - Cancel: `cancelTransferIn(address tokenAddress, …)` (L337), reachable only from `CrossChain.cancelTransfer` (CrossChain.sol v1.1.9 L501–507).
4. **Accounting.**
   - A per-transfer threshold. There is no cumulative cap and no window.
   - Defaults (L95–96): `INIT_BNB_LARGE_TRANSFER_LIMIT = 10000 ether`, `INIT_LOCK_PERIOD = 12 hours`.
   - Governance bounds (L629–637): lock period ≤ 1 week; BNB threshold ≥ 100 BNB.
5. **Control.**
   - The BEP-20 token owner sets its threshold (L308, `onlyTokenOwner`).
   - BSC governance sets the BNB threshold and the lock period.
   - The BSC "cabinet" validators can suspend (quorum `INIT_SUSPEND_QUORUM = 1`), reopen (2) and cancel (2), with proposals expiring after 1 hour (CrossChain.sol L52–55, L133–141, L486–507).
   - Transfers are authenticated by Beacon Chain headers in the BSC light client, so the cabinet is not the header-signing set. **Not the verifier set** (overlap not checked).
   - **Current state.** At master the transfer-in handler reverts (`TokenHub.sol` L127–131 `revert("deprecated");`). The large-transfer fields are marked `// @dev deprecated` (L38, L42). A 7-day lock now applies to token recovery from the retired Beacon Chain (L40 `LOCK_PERIOD_FOR_TOKEN_RECOVER = 7 days`, L229–235).

### 2.17 xERC20 reference (ERC-7281)

**Repository:** xERC20 @ `da2afab`, `solidity/contracts/XERC20.sol`.

1. **Where.** In the token contract, per bridge address:
   - `mint` (L48–50) → `_mintWithCaller` L278 `if (_currentLimit < _amount) revert IXERC20_NotHighEnoughLimits();`;
   - `burn` → L262, the same check.
   - The lockbox is exempt (L276 `if (_caller != lockbox) {`).
2. **Direction.** Both: a mint bucket and a burn bucket per bridge.
3. **At the limit.** Revert. Retry depends on the calling bridge.
4. **Accounting.**
   - Token bucket over one day (L13 `_DURATION = 1 days`; L180 `ratePerSecond = _limit / _DURATION`; L243–248 refill capped at max).
   - **Gross:** burns do not restore mint capacity.
   - Token units.
5. **Control.** `setLimits` is `onlyOwner` (L85): the token issuer. **Not the verifier set** of any bridge.

### 2.18 Taiko QuotaManager

**Repository:** taiko-mono @ `7194497`. File paths are relative to `packages/protocol/`.

1. **Where.** Destination release.
   - ETH: `contracts/shared/bridge/Bridge.sol` L365 `_consumeEtherQuota(status_ == Status.DONE ? _message.value + _message.fee : _message.fee);`.
   - Tokens: `contracts/shared/vault/ERC20Vault.sol` L451 `_consumeTokenQuota(token, amount);`.
   - The quota manager is optional: the Bridge stores it as an immutable that may be zero (Bridge.sol L159).
2. **Direction.** Inbound releases on each chain.
3. **At the limit: revert, retryable.**
   - `contracts/shared/bridge/QuotaManager.sol` L91 `if (available < _amount) revert QM_OUT_OF_QUOTA();`.
   - A token release that fails leaves the message `RETRIABLE` (Bridge.sol L357). The retry consumes on success (L436). The ETH path reverts `processMessage`, and the message stays new.
   - There is no deadline.
4. **Accounting.**
   - Token bucket (L123 `uint256 issuance = q.quota * elapsed / quotaPeriod;`, capped at quota). A quota of 0 means unlimited (L109).
   - Gross, per token, token units.
   - `updateQuota` refills to full (L76 `tokenQuota[_token] = Quota(0, _quota, _quota);`).
   - Deploy script (`script/layer1/mainnet/DeployQuotaManager.s.sol` L24–31): `15 minutes`, `uint104 value = 200_000; // USD`, `uint104 priceETH = 1750; // USD`.
5. **Control.** The owner sets quotas (L70, `onlyOwner`). The Bridge pauses by owner or pauser (Bridge.sol L556). Messages are proof-verified. **Not the verifier set.**

### 2.19 THORChain outbound delay and solvency halt

**Repository:** thornode @ `8eb2d08`.

1. **Where.** At the verifier.
   - The node set schedules each outbound at a future height. The vault's threshold signers sign it at that height.
   - The solvency check runs on node reports in the state machine.
2. **Direction.** Outbound (and refunds) from THORChain vaults.
3. **At the limit.**
   - **Delay** (`x/thorchain/manager_txout_current.go` `CalcTxOutHeight`, L1288–1384).
     - The delay rate falls as scheduled volume rises (L1348–1353): `rateReduction := … Mul(common.SafeSub(sumValue, cloutValue)).Quo(minVolumeThreshold)`, then `delayRate = delayRate.Sub(rateReduction)`, floored at 1.
     - `minBlocks := runeValue.Quo(delayRate)`, capped at `MaxTxOutOffset` (L1357–1361).
     - The item then moves to the first later block whose scheduled value plus the item fits under `MinTxOutVolumeThreshold` (L1365–1381, `for count < txOutDelayMax {`), searching at most `TxOutDelayMax` blocks.
     - **Release is automatic at the scheduled height.** There is no cumulative cap, only a per-block soft cap over a horizon of `TxOutDelayMax` blocks.
     - Defaults (`constants/constants_v1.go` L76–79): `MinTxOutVolumeThreshold` 1000_00000000, `TxOutDelayRate` 25_00000000, `TxOutDelayMax` 17280, `MaxTxOutOffset` 720. Live mimir values are in the deploy note.
   - **Solvency halt.** When a supermajority of node reports shows a vault's wallet below the ledger by more than `PermittedSolvencyGapUSD` (L86: `500_00000000, // $500 USD in 1e8 notation`), the chain halts:
     - `x/thorchain/handler_solvency_helpers.go` L395 `if gapInRune.GT(permittedGapInRune) {` → insolvent;
     - L173 `k.SetMimir(ctx, haltChainKey, ctx.BlockHeight())` with key `SolvencyHalt%sChain` (L109);
     - `keeper/v1/keeper_halt.go` L103–108 makes `IsChainHalted` true;
     - L57 of `handler_solvency.go`: bifrost "will not observe inbound, and will not sign outbound txs".
     - **The halt lifts automatically** when a later report shows solvency (L188–191 `if !isInsolvent && haltChain > 1 {` … `k.SetMimir(ctx, haltChainKey, 0)`).
     - The code comment (L55) still says 1%. The 100 bps constant `PermittedSolvencyGap` (L85) is not used in `insolvencyCheck`.
4. **Accounting.**
   - Delay: RUNE value of each outbound at pool prices, against aggregate scheduled value. The swapper's "clout" reduces it (L1316).
   - Halt: wallet balance against the ledger, per vault and chain.
5. **Control.**
   - Node operators set all parameters by mimir votes (`handler_mimir.go` L169–175, supermajority or operational minimum). They can disable the checker per chain (`StopSolvencyCheck…`, `handler_solvency_helpers.go` L101–107).
   - A single active node can pause all chains for `NodePauseChainBlocks` = 720 blocks (`handler_node_pause_chain.go` L80–93; constants L55).
   - **Same parties as the verifier set.**

### 2.20 ERC-7265 reference implementation (circuit breaker)

**Repository:** v1-core @ `3960a05`.

1. **Where.** Destination release. The protected contract routes each outflow through the breaker (`src/core/CircuitBreaker.sol` `onTokenOutflow`, L131–138) and reports each inflow (`onTokenInflow`, L127).
2. **Direction.** Outflows, netted against reported inflows.
3. **At the limit.**
   - **Trigger.** Net outflow within the sliding period pushes liquidity below the retained share of the period-start reference: `src/utils/LimiterLib.sol` L118 `if (limiter.limitBeginThreshold > uint256(currentLiq)) { return LimitStatus.Inactive; }`; L122–126 `int256 futureLiq = currentLiq + limiter.liqInPeriod; int256 minLiq = (currentLiq * int256(limiter.minLiqRetainedBps)) / int256(BPS_DENOMINATOR); return futureLiq < minLiq ? LimitStatus.Triggered : LimitStatus.Ok;`.
   - The **caller chooses revert or hold** per call (`_revertOnRateLimit`).
   - **Hold path.**
     - The outflow is recorded first (L300). The tripping outflow and all later outflows go to `lockedFunds` (L306, L320), and the global flag is set (L317 `isRateLimited = true;`).
     - **After `rateLimitCooldownPeriod` anyone lifts the flag** (`overrideExpiredRateLimit`, L178–185; no caller check).
     - Anyone then claims for the recorded recipient (`claimLockedFunds`, L156–166). It reverts only while the flag is set (L158).
   - The admin can also lift the flag immediately with a grace period (`overrideRateLimit`, L206–211), start any grace period (L226–229), or freeze everything (`markAsNotOperational`, L255–257) and move all funds to a recovery address (L259–273).
4. **Accounting.**
   - A sliding period with tick buckets (`LimiterLib.sol` L39–76; `sync` L78–109). Per token, in token units.
   - **Geometric**: the cap is a share of current liquidity.
   - **Net**: a counted inflow is whatever the protected contract reports through `onTokenInflow`. In a bridge integration that is a real deposit.
   - One global flag covers all tokens.
5. **Control.** The admin (protocol governance). There is no verifier concept. **Not the verifier set.**

---

## 3. Classification

Stage key: **V** = verifier, **S** = source send, **D** = destination release, **T** = token.

| Rule | Stage | Shape | Gross or net (cost of a counted inflow) | Automatic release | Controlled by verifier set |
|---|---|---|---|---|---|
| Wormhole Governor | V (keyed to source chain) | **cliff** at 24 h (sliding 24 h cap before) | gross; net if a Guardian enables flow cancelling (inbound USDC/USDT/DAI-variant transfer on the Ethereum–Sui corridor, as published by the Guardian; banks within the window) | yes, 24 h, not counted | **yes** |
| Wormhole Global Accountant | V | **bounded** (releases ≤ recorded locks) | conservation ledger (lock or burn observed by a quorum) | no (dropped) | **yes** |
| Wormhole NTT | S + D | ramp; **cliff** for queued items after `rateLimitDuration` (default 24 h; inbound always queues) | net (release side refilled by real burns or locks of the same token sent from the releasing chain; capped at the limit) | yes, permissionless, not counted | no (integrator owner) |
| Chainlink CCIP pools | S + D | **ramp** (token bucket) | gross | no (failed message retryable, retry consumes) | no |
| LayerZero OApp RateLimiter | S (integrator) | **ramp** | optional net, integrator-defined | no | no |
| LayerZero Stablecoin/RWA OFT | S + D | **ramp** | optional net (real burn or lock of the same token on the releasing chain; capped) | no (retry consumes) | no |
| Axelar ITS | S + D (+ Hub supply check at V) | **ramp** (fixed 6 h epochs) | net within epoch (real burn or lock of the same token on the releasing chain; banks within epoch) | no | partly (token operator; ITS operator) |
| Axelar legacy gateway | D | **ramp** (fixed 6 h epochs); none where limit = 0 | gross | no (command retryable) | partly |
| Hyperlane RateLimitedHook / RateLimitedIsm | S / D | **ramp** | gross | no | no |
| Hyperlane NetFlow / DelayedFlow (HEAD) | S + D (credit at S, consume at D) | **geometric** (bps × live TVL); DelayedFlow adds a **cliff** at `maxDelay` | net (real deposit of the same token into the router) | DelayedFlow yes (≤ `maxDelay`, counted as debt) | no |
| Circle CCTP | S (burn cap); T (USDC minter allowance) | per-message cap at source; **bounded** at token | n/a (allowance gross) | n/a | **yes** (Circle) |
| Linea | D (L1 claim) + S (L2 send) | **ramp** (fixed period anchored at first use) | gross (ETH and fees only) | no | no |
| StarkGate | D (L1) + S (L2) | **geometric** (5% of balance per UTC day; off for ETH and STRK on 2026-10-16) | gross within day (deposits raise the next day's base) | no | no |
| Ronin | D | **ramp** (UTC day) below `lockedThreshold`; **bounded** at or above it | gross | no (unlocker role) | partly (paired governor keys) |
| Celer cBridge | D | **ramp** (fixed epochs) plus fixed delay for large items | gross | yes (`delayPeriod`, counted when queued) | no |
| Gnosis OmniBridge / xDai | S + D | **ramp** (UTC day) | gross | no (OmniBridge: fail and refund; xDai Gnosis side: held for owner) | no |
| BNB Chain BEP-171 | D | **cliff** (12 h; per-transfer threshold, no cap) | n/a | yes, permissionless | no (cabinet ≠ header signers) |
| xERC20 reference | T | **ramp** (per-bridge mint and burn buckets) | gross | no | no |
| Taiko QuotaManager | D | **ramp** | gross | no (retriable) | no |
| THORChain outbound delay | V | ramp (per-block soft cap) to a horizon of `TxOutDelayMax` blocks, then **cliff** | n/a | yes | **yes** |
| THORChain solvency halt | V | **bounded** (halt while ledger exceeds wallet by > $500) | wallet vs ledger | auto-unhalt when solvent | **yes** |
| ERC-7265 reference | D | **geometric**; in hold mode a **cliff** after the cooldown | net (inflow reported by the protected contract) | hold mode yes (anyone lifts after cooldown) | no (admin) |

## 4. Differences from the deploy note found in code

1. **Linea** is not a calendar window. The period restarts at the first use after it expires (§2.11). Only ETH value and fees are metered; ERC-20 bridging is not.
2. **CCTP.** The per-message cap binds burns only, and CCTP mints do not check it. The cumulative bound on mints is USDC's minter allowance (on Ethereum, 108.19M for V1 and 1,168.70M for V2 on 2026-10-16).
3. **StarkGate.** The daily allowance is a share of the balance at the day's first withdrawal, with no in-day netting. On 2026-10-16 the L1 limit was off for ETH and STRK. The L2 default in code is 5% of supply, against 8% in the forum post.
4. **Wormhole Governor.** The timer reset accepts up to 90 days in code, against 30 in the whitepaper. Flow cancelling is limited to five token entries on one corridor, Ethereum–Sui.
5. **Wormhole NTT.** Inbound transfers have no revert option and no cancel function. Queued items are released by anyone after the duration and skip the bucket.
6. **Gnosis OmniBridge.** An over-limit release is not held until the day resets. The message fails, and the sender is refunded on the origin chain through `requestFailedMessageFix`. "Wait for reset" describes only the xDai bridge's Ethereum side (revert and retry); the Gnosis side holds the transfer for the owner.
7. **Celer.** Delayed transfers count against the epoch cap when queued. A change to `delayPeriod` applies to items already queued.
8. **Hyperlane** at HEAD adds three variants: TVL-proportional net-flow limits, and a delayed-flow variant that waits up to `maxDelay` and then releases.
9. **BEP-171** is retired at master. The transfer-in handler reverts.
10. **THORChain.** The solvency threshold in code is an absolute $500 equivalent, not 1%. A halt lifts automatically when solvency returns.
11. **CCIP.** v2.0 refills a bucket to full on any parameter change; v1.6 does not. Neither commit has a lane-level USD limiter.
12. **LayerZero Stablecoin/RWA OFT.** Pause by ID covers sends only, not inbound credits.

## 5. Not established here

- Whether each deployed contract matches these commits (no bytecode comparison).
- Who holds the roles: CCIP pool owners, NTT owners, Hyperlane route owners, Linea and Ronin admins, Celer governors and Sentinel use, Gnosis owner keys.
- Which LayerZero OFTs and Hyperlane routes use which variant.
- The Axelar ITS Hub call sites.
- Where the Axelar nexus rate limit went after v1.2.0.
- THORChain live `TxOutDelayMax`.
- The bifrost check that refuses signatures for outbounds that would leave a vault insolvent (described in THORChain docs). It is not in `bifrost/signer/sign.go` at `8eb2d08`, and other bifrost files were not read.
