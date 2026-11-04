# Who controls the deployed limits, and three deployment facts

Prepared 2026-10-16 for the paper on bridge withdrawal limits. Companion to `limiter_code_facts.md` (same pinned commits; line numbers refer to those commits). The per-rule table is in `rules_controls.csv`. These are reading notes, not verified statements.

Sources added in this pass:
- `axelar-gmp-sdk-solidity` main: `contracts/governance/InterchainGovernance.sol`, `AxelarServiceGovernance.sol`, `contracts/utils/TimeLock.sol` (raw GitHub fetch, 2026-10-16).
- `axelar-contract-deployments` main: `axelar-chains-config/info/mainnet.json` (raw GitHub fetch, 2026-10-16).
- Chainlink CCIP documentation, full text at `docs.chain.link/ccip/llms-full.txt` (fetched 2026-10-16; WebFetch to docs.chain.link failed, curl succeeded). Pages quoted are named by their `Source:` URL.

What was not read: on-chain role holders for any rule except where `limiter_code_facts.md` already records them. "No timelock in contract" means the contract imposes none; the holder of the role may itself be a timelock or multisig, which was not checked unless stated.

## 1. Pause and parameter control, rule by rule

Categories for "who": **verifier set** (the parties whose attestations authorize messages), **token issuer**, **separate party** (route deployer, bridge operator multisig, security council), **governance vote**.

| Rule | Pause releases | Change limit parameters | Delay | Who |
|---|---|---|---|---|
| Wormhole Governor | No on-chain pause. Each Guardian withholds signatures or drops/extends queued messages through its admin RPC (`governor_monitoring.go` L160–239; extension cap 90 days, `adminserver.go` L46). Seven of 19 withholding stop a message. | Limits compiled into node software (`mainnet_chains.go` L13–24); each Guardian enables the rule and flow cancelling by flag (`node.go` L566–567). | No timelock; a change takes effect as Guardians adopt a release. | Verifier set |
| Wormhole Global Accountant | No pause; per-node enforce flag (`node.go` L414). | Governance message `ModifyBalance` needs a Guardian quorum (`global-accountant/src/contract.rs` L267, L410). | None in code | Verifier set |
| Wormhole NTT | `pause()` owner or pauser; `unpause()` owner only (`ManagerBase.sol` L338–342). | Owner: `setOutboundLimit`, `setInboundLimit`, transceivers, threshold, upgrade (`NttManager.sol` L137–150). | None in contract | Separate party (integrator, usually the issuer) |
| Chainlink CCIP pools | RMN curse of a chain or global subject. v2.0: owner or authorized curse admins curse, owner uncurses (`rmn/RMN.sol` L39–95). v1.6: owner curses and uncurses (`RMNRemote.sol` L200–237). Pool owner or `rateLimitAdmin` can also set capacity 0 per lane (docs, rate-limits/emergency-actions). | Pool owner or `rateLimitAdmin` (`TokenPool.sol` L872–942). | Pool: none in contract. CCIP-owned contracts: "All onchain configuration changes must pass through a Role-Based Access Control Timelock (RBACTimelock)", with a node-operator veto window or an "explicit approval" path by signer quorum for urgent fixes (docs, v1/evm/concepts/architecture/onchain/upgradability). Window length not stated on that page. | Pool: token issuer. Curse: CCIP owner (Chainlink multisig and timelock) |
| LayerZero OApp RateLimiter | No pause in the library. The OApp owner or delegate can `nilify` or `burn` verified messages at the endpoint (`MessagingChannel.sol` L95, L112; `EndpointV2.sol` L353–356). | `_setRateLimits`, `_resetRateLimits` as exposed by the integrator (`RateLimiter.sol` L175, L195). | None in contract | Separate party (application owner) |
| LayerZero stablecoin/RWA OFT | `PAUSER_ROLE` pauses sends per destination ID; inbound credits carry no pause modifier (`OFTBurnMintExtendedRBACUpgradeable.sol` L97–122). Inbound stops only via rate-limit config or endpoint `nilify`/`burn`. | `RATE_LIMITER_MANAGER_ROLE` (configs, exemptions, overwrite of usage) (`RateLimiterRBACUpgradeable.sol` L27–86). | None in contract | Token issuer |
| Axelar ITS | ITS operator or owner, `setPauseStatus` (ITS L647). | Token `FLOW_LIMITER` (token operator; ITS while it holds the role) (`TokenManager.sol` L112–167); ITS operator in bulk (ITS L617). | None in ITS. Axelar governance contracts: `AxelarServiceGovernance` with `minimumTimeDelay` 259,200 s (3 days) on 17 chains, `InterchainGovernance` 604,800 s (7 days) on 2 entries (deployment config). Operator proposals approved by the Axelar network vote execute without the timelock (`AxelarServiceGovernance.sol`, `executeOperatorProposal`). Whether ITS's owner is that contract was not read. | Partly verifier set (Axelar-side roles), partly token issuer |
| Axelar legacy gateway | Pauser or governance (`AxelarGateway.sol` L129–135). | Mint limiter or governance (`setTokenMintLimits`, L414; modifier L122). | Governance proposals come from an Axelar network vote and the timelocks above; binding not read. | Partly verifier set (validator governance) |
| Hyperlane rate-limited hook/ISM | Only if the route composes `PausableIsm`/`PausableHook` (owner, `PausableIsm.sol` L35–39). | Route owner, `setRefillRate` (`RateLimited.sol` L162). | None in contract | Separate party (route deployer) |
| Hyperlane net-flow / delayed-flow | Same; `DelayedFlowRouterHookIsm` notes recommend composing `PausableIsm` (L43–44). | Route owner (`TvlRateLimited.sol` L182–184). | None in contract | Separate party |
| Circle CCTP | Circle pauser (`MessageTransmitter.sol` `whenNotPaused` L112–253). | Circle token controller (burn cap), attester manager, USDC master minter (minter allowance). | None in contract | Verifier set (Circle attests and issues) |
| Linea | Role mapped to pause type `L2_L1`: pause expires after 48 h, then 48 h cooldown; `SECURITY_COUNCIL_ROLE` pauses indefinitely; anyone lifts an expired non-council pause (`PauseManager.sol` L14–28, L154–240). | `RATE_LIMIT_SETTER_ROLE`; `USED_RATE_LIMIT_RESETTER_ROLE` zeroes usage (`RateLimiter.sol` L14–117). | None in contract; holders not read | Separate party (operator and security council) |
| StarkGate | No pause on L1 `withdraw`. Security agent can enable the limit (L349); manager can deactivate a token (L239). | Security admin disables the limit (L357). The percentage is set only at initialization or in an upgrade initializer (`WithdrawalLimit.setWithdrawLimitPct` callers: `StarknetTokenBridge.sol` L116, `ConfigureSingleBridgeEIC.sol` L63). | Enable/disable immediate; percentage changes through an upgrade (proxy delay not read). | Separate party (council multisig per forum post) |
| Ronin | Proxy admin or `emergencyPauser` (`GatewayV3.sol` L26, L113). | Proxy admin (`WithdrawalLimitation.sol` L109–160); held items released by `WITHDRAWAL_UNLOCKER_ROLE`. | None in contract | Partly verifier set (operators paired with governor keys) |
| Celer cBridge | Pausers (`Pauser.sol` L18–39); under Sentinel, unpause needs relaxed mode. | Governors (`Governor.sol` L13–30); under Sentinel, without guard consent they may only tighten (`GuardedGovernor.sol` L84, L124). | None; relaxation needs `relaxThreshold` guards (`Guard.sol` L104). A change to `delayPeriod` applies to items already queued. | Separate party |
| Gnosis OmniBridge / xDai | No pause function. Owner can set execution limits to 0; over-limit OmniBridge releases then fail and refund. | Owner (`TokensBridgeLimits.sol` L145–194). | None in contract | Separate party (owner multisig) |
| BNB Chain BEP-171 | Cabinet validators: suspend quorum 1, reopen and cancel quorum 2, proposals expire after 1 h (`CrossChain.sol` v1.1.9 L52–55, L133–141, L486–507). | BEP-20 token owner (its threshold, `TokenHub.sol` L308); BSC governance (BNB threshold, lock period ≤ 1 week, L629–637). | Governance voting period not read | Separate party; governance vote for system parameters; token issuer for its threshold |
| xERC20 | No pause; owner can set a bridge's mint limit to 0. | Token owner, `setLimits` (`XERC20.sol` L85). | None in contract | Token issuer |
| Taiko QuotaManager | Bridge owner or immutable pauser (`Bridge.sol` L556). | QuotaManager owner, `updateQuota` (L70). | None in contract | Separate party (rollup owner) |
| THORChain outbound delay | One active node pauses all chains for 720 blocks (`handler_node_pause_chain.go` L80–93); mimir halts by vote. | Node mimir votes (`handler_mimir.go` L169–175). | None; effective at the vote threshold | Verifier set |
| THORChain solvency halt | Automatic on a supermajority of insolvency reports; nodes can stop the checker per chain. | Node mimir votes. | None | Verifier set |
| ERC-7265 (draft) | Admin: `markAsNotOperational`, `overrideRateLimit`, grace periods (`CircuitBreaker.sol` L206–257). | Admin: `registerAsset`, `updateAssetParams` (L187–200). | None in contract | Governance of the protected protocol |

Patterns:
- **Pause is immediate everywhere it exists.** No rule in the sample puts a timelock on pausing. The only time structure on a pause is Linea's 48 h expiry for non-council pausers.
- **Parameter changes are immediate in the contract for every on-chain rule.** The only timelocks found sit above the contracts, in the owner's governance: CCIP's RBACTimelock with a veto window or a quorum bypass, and Axelar's governance contracts (3 or 7 days, with an operator path that skips the delay).
- **Releases cannot be paused at all** in four rules: StarkGate L1 withdraw, Gnosis OmniBridge (limits can be set to 0, which fails and refunds), xERC20 (mint limit to 0), LayerZero OFT inbound (pause covers sends only).
- **Verifier set holds both controls** for the Wormhole Governor and Accountant, Circle CCTP, and THORChain. Axelar and Ronin are partial. All other rules sit with the token issuer or a separate operator.

## 2. Chainlink CCIP Risk Management Network

**What it can do.** It curses subjects. A subject is a chain selector or a global subject. "The RMN program lets an owner curse any blockchain (by chain selector) or declare a global curse through the `curse` instruction that halts all CCIP traffic. Once cursed, any CCIP transaction that performs the verification check for that chain selector (or the global curse) will revert" (docs, v1/svm/concepts/architecture/onchain/components). The current overview: "Curse: A manual onchain safety flag set via the RMN contract. When a chain or lane is cursed, sends and executions involving it revert until the curse is lifted" (docs, ccip/concepts/architecture/overview). In code, token pools revert with `CursedByRMN` in both `lockOrBurn` and `releaseOrMint` (`TokenPool.sol` L422, L479), and the v1.6 OffRamp checks the curse at commit and at execution (`OffRamp.sol` L381, L832).

**Blessing.** In v1.6 code, commit reports carry RMN node signatures on Merkle roots. `RMNRemote.verify` requires `fSign + 1` signatures from a configured signer set of at least `2fSign + 1` nodes (`RMNRemote.sol` L51, L96–153). A per-source-chain flag `isRMNVerificationDisabled` turns this off (`OffRamp.sol` L110, L840).

**Who operates it now.** The documentation states that the automated off-chain network is not running: "the Risk Management Network's automated offchain role is no longer active in current CCIP deployments, but is expected to be offered as an optional validation layer in future releases. The onchain RMN contract remains part of CCIP's architecture as an emergency safeguard" (docs, v1/concepts/architecture/key-concepts and v1/evm/concepts/architecture/onchain/components). Cursing is manual: "When the CCIP Owner manually initiates a curse, the `curse()` function is invoked" (docs, v1/evm/.../onchain/components). In code:
- v2.0 `RMN.sol`: the owner and an `AuthorizedCallers` set of curse admins may curse; only the owner uncurses (L39–95).
- v1.6 `RMNRemote.sol`: only the owner curses and uncurses (L200–237); the owner also sets the blessing signer set (L140).
- CCIP owner actions go through ManyChainMultiSig and an RBACTimelock, with signers "selected from multiple high-quality Chainlink node operators … as well as from Chainlink Labs" (docs, v1/evm/concepts/architecture/onchain/upgradability).

**Is it separate from the committing network?** As designed in v1.6, yes: a separate signer set whose blessing is checked independently of the committing DON's OCR signatures. As deployed now, by the documentation, no independent off-chain network is active. The remaining control is a curse flag held by the CCIP owner (and in v2.0 by curse admins the owner appoints). That owner is a Chainlink-operated multisig and timelock, not the committing DON. In v2.0 messages are attested by a "Committee Verifier" of "16 independent node operators" plus optional CCVs (docs, ccip/concepts/architecture/overview); the curse is a separate on-chain switch above them. Whether curse admins on mainnet are separate from the committee operators was not read.

## 3. How the Wormhole Governor values tokens

**The larger of a configured price and the CoinGecko price, when CoinGecko answers; the configured price alone when it does not.**
- `governor_prices.go` header L3–5: "The initial prices are read from the static config … After that, prices are queried from CoinGecko. The chain governor then uses the maximum of the static price and the latest CoinGecko price."
- `updatePrice` L308–315: `if (te.coinGeckoPrice == nil) || (te.coinGeckoPrice.Cmp(te.cfgPrice) < 0) { te.price.Set(te.cfgPrice) } else { te.price.Set(te.coinGeckoPrice) }`.
- On a failed or missing response the price reverts to the configured price, not the last market price (L232–244, `revertAllPrices` L290–303). Polling interval: 120 minutes (L32).
- The configured prices come from a generated list (`generated_mainnet_tokens.go`, header "generated: Mon Sep 21 2026 … using a min notional of 0"). They are prices at generation time, refreshed only when the list is regenerated and shipped in a node release.
- The notional is `amount × price` (`governor.go` L1013), computed when the transfer is processed and stored as `ScaledValue` in the 24 h list (L656, L921). Entries are not revalued when prices move. Queued items are revalued at the current price when the queue is re-checked (L845).
- Effect: the configured price acts as a floor. A market crash does not lower the Governor's valuation below the floor, so the limit binds in token units sooner. A market rise above the floor lowers the token-unit allowance.

## 4. Net accounting: can a round trip raise the releasing side's allowance?

The question for each rule: a party deposits on chain A and receives the value on chain B. Does that deposit raise the allowance for releases on A, and is the matching release on B itself limited, queued or held?

**Wormhole NTT (backflow).**
- Counted inflow for A's inbound (release) bucket from B: a non-queued outbound send from A to B, which burns or locks the same token on A (`NttManager.sol` L529–532). The refill saturates at the limit. Queued outbound items that complete later skip the limit and do not backfill (L356).
- The send also consumes A's outbound bucket (L528). That bucket is refilled by inbound releases on A (L312), including unbacked ones.
- The matching release on B passes B's inbound bucket from A. Over the limit it is queued, and after `rateLimitDuration` (24 h) anyone releases it without counting it (L317–335).
- Verdict: **yes, at the cost of B's inbound capacity or a 24 h wait.** Each unit sent from A to B restores one unit of A's release capacity, up to the cap. The depositor receives the same tokens on B, so the capital is recovered on B. B's limit delays the round trip but does not cap its volume, because queued inbound items are released uncounted after 24 h. Returning the capital to A through NTT consumes A's inbound bucket, so recycling needs another route or a market sale on B.

**Axelar ITS flow limits.**
- Counted inflow for releases on A (flow-in): flow-out on A in the same 6 h epoch, a real burn or lock of the same token (`TokenHandler.sol` L88; `FlowLimit.sol` L124–127). Surplus banks within the epoch: deposits of X allow releases up to X + L.
- The matching release on B is a flow-in on B. It reverts if |in − out| on B would exceed B's limit, and is retryable later (no queue) (`FlowLimit.sol` L115–127).
- Verdict: **yes, bounded per epoch by B's flow limit plus B's own outflows in that epoch.** The single-transfer cap L applies on both sides. The express path does not change this: the flow-in on B is counted when the approved message repays the express executor (ITS L715–718).

**Hyperlane `NetFlowRateLimitedHookIsm`.**
- On a collateral router A, dispatch credits A's bucket (`NetFlowRateLimitedHookIsm.sol` L195–197). The deposit also raises A's TVL, and so its capacity (`TvlRateLimited.sol` L157). Credits saturate at capacity (`RateLimited.sol` L204–218).
- On the synthetic router B, an inbound delivery (a mint) **credits** B's bucket rather than consuming it (`verify`, L166–170). Only outbound burns on B consume.
- Verdict: **yes, and the matching mint on B is not limited by this module.** A deposit on A restores A's release capacity one for one, and the depositor receives synthetic tokens on B with no rate limit on the mint. The deposit stays in A's collateral, and the library notes say so: "raising the balance to lift the cap also funds the pool the cap gates, so the actor pays for the headroom" (L38–40). Under unbacked releases from A that collateral leaves again, and the synthetic tokens on B are left unbacked. The depositor's cost is holding the synthetic token, or its sale price on B.
- `DelayedFlowRouterHookIsm`: origin deposits credit 1:1 (L134). The matching release is delayed by the deficit, at most `maxDelay`, and then released automatically.

**LayerZero stablecoin/RWA OFT (optional netting).**
- Counted inflow for A's inbound usage: an outbound `_debit` on A (a real burn or lock), when `netAccountingEnabled` (`RateLimiterBaseUpgradeable.sol` L348–349). Saturates at zero usage.
- The matching release on B is `_credit` on B, subject to B's inbound limit. It reverts and is retryable later, with no queue (RLB L338–341; `EndpointV2.sol` L172–181).
- Exempt addresses skip the rule entirely (RLB L314).
- Verdict: **yes, bounded by B's inbound limit per window.** The generic OApp `RateLimiter` netting is integrator-defined (`_inflow` optional); its behaviour depends on where the integrator calls it.

**Wormhole Governor flow cancelling.**
- Counted inflow: a token-bridge transfer emitted on the corridor partner and published by this Guardian. It enters as a negative entry in the destination chain's 24 h list (`governor.go` L1092). Only the Ethereum–Sui corridor and listed USDC/USDT/DAI variants qualify. Big transfers and timer-released transfers do not count. Surplus banks within the 24 h window (L1131).
- Mapping to the question: a deposit on Sui toward Ethereum raises Ethereum's emitted-value allowance, i.e. the allowance for transfers from Ethereum that are released on Sui.
- The matching release on Ethereum carries a message emitted on Sui, so it is itself governed by Sui's Governor: daily limit $2.5M, big-transfer size $250k (`mainnet_chains.go` L24). Over the limit it is queued for 24 h and then released. A timer-released item does not count as an offset.
- Verdict: **yes, bounded by Sui's governed outflow.** At most $2.5M of counted offsets per 24 h, in pieces below $250k each, using real stablecoin deposits on Sui. The depositor receives the stablecoin on Ethereum.

**ERC-7265 (draft).** The counted inflow is whatever the protected contract reports through `onTokenInflow`. The rule is single-chain; the other side is not part of the reference implementation.

**Common answer.** In every net rule the counted inflow is a real deposit of the same token on the releasing chain. A round trip therefore restores release capacity on that chain one for one, up to the bucket cap or the window. The price of the round trip is not the deposit itself, which the party gets back on the other side. It is the capacity of the other side's limit, plus fees and the time capital is tied up. That capacity is a revert-and-retry limit (ITS, OFT), a 24 h queue that releases without counting (NTT, Governor), or no limit at all for synthetic mints (Hyperlane net-flow). Under an unbacked-release failure on chain A, each round-trip unit lets one more unbacked unit leave A, and leaves one unit on B without backing.
