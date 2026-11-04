# Verifier stake and bonds versus value held and moved: cross-chain bridges

Prepared 2026-10-16 for the bridge withdrawal-limit paper. The deployed outflow-limit rules it refers to ("§1.x") are those of an earlier rule list of the authors; `limiter_code_facts.md` describes the same rules.

**Conventions**

- **Access times.** Web pages and APIs were read between 2026-10-15 23:40 UTC and 2026-10-16 00:25 UTC. Each source line gives its UTC access date.
- **Ethereum reads.** `eth_call`, `eth_getBalance` and `eth_getCode` pinned to block **26,201,369** (timestamp 2026-10-16 00:00:59 UTC), sent to https://ethereum-rpc.publicnode.com (fallback https://rpc.mevblocker.io, not needed). Method and contract list in §6.
- **Axelar reads.** Cosmos REST (LCD) queries to https://axelar-rest.publicnode.com at Axelar height 36,297,293 (2026-10-16 00:06 UTC).
- **Prices.** DefiLlama coins API, current prices at 2026-10-16 00:08 UTC. CoinGecko simple-price at the same minute agrees within 2% for every native token used (largest gap AXL: 0.05496 vs 0.05601). Prices used: ETH 2,441.33; LINK 12.4526; POL 0.095476; AXL 0.054960; HYPER 0.066258; ZRO 2.0924; UMA 0.39280; BARD 0.11166; SIS 0.017496; LBTC 82,272; SolvBTC 81,769.
- **Terms.**
  - *Stake*: collateral that verifiers post, or that is delegated to them, and that is tied to their role.
  - *Slashable for invalid messages*: a published rule lets a third party show that verifiers attested to a message with no matching source-chain event, after which stake is confiscated.
  - *Value held*: assets in escrow or lock contracts that are released on verified messages. *Value moved*: transfer volume.
  - *Flow quantity*: what a deployed limit lets out within a response time d (the comparison object of the paper).
- **Ratios.** "Stake / value" is stake over value held, the stock condition. §5 compares stake with flow quantities where a limit exists.

---

## 0. Key facts

1. **No bridge in scope meets the stock condition.** The highest ratios are Polygon PoS (0.16 of escrow read on-chain) and Axelar (0.087). Neither stake can be slashed for invalid messages.
2. **Only two live arrangements publish rules that confiscate stake for invalid attestations.**
   - Hyperlane's HYPER vault on Symbiotic: 19.94M HYPER ($1.32M) against $76.5M held by Hyperlane routes (ratio 0.017).
   - EigenZero, an optional LayerZero DVN: $5M of ZRO announced; the stake was not located on-chain.
   - In both, a council approves or can veto each slash.
   - Lombard's BARD vault for LBTC transfers over CCIP has an on-chain veto slasher (3-day veto) but no published slashing conditions. It holds $144k.
3. **The large stakes are not slashable for invalid messages.**
   - Polygon validators: $342M. The deployed StakeManager has no slash entry point.
   - Chainlink Staking v0.2: $529M. It covers staleness of the ETH/USD feed only, at 700 LINK per node operator, and does not cover CCIP.
   - Hyperlane's EigenLayer AVS: registered weight of roughly 1.43M ETH-equivalent. Its docs say slashing is not enabled.
   - Axelar validators: $16.0M. Slashing applies only to double signing (2%) and downtime (0.01%).
4. **Optimistic bonds are small next to the value they settle.**
   - Across root-bundle proposers bond 0.45 ABT ($1,099) for a 30-minute window, against $17.85M of LP reserves.
   - Disputes go to UMA's DVM, where 19.40M UMA ($7.62M) is staked.
5. **Several Symbiotic vaults set up for bridges held zero stake at the block read:** Solv CCIP, Ethena rsENA and rsUSDe (for LayerZero DVNs), and Cycle.
   - The LINK vault shared by the Lombard and Solv CCIP networks holds 790 LINK ($9.8k) and has no slasher configured.
6. **Where a deployed limit gives a flow quantity, stake is still far below it.**
   - LBTC's CCIP inbound buckets let out 4,950 LBTC ($407M) when full and $543M within one hour. The BARD stake is 0.035% and 0.027% of these.
   - Wormhole has no stake. Its Governor caps (sum $42.5M per sliding 24 h over ten chains) are applied by the guardians themselves.
7. **Stake withdrawal delays against dispute windows.**
   - EigenLayer deallocation 14 d, against EigenZero's 11-day review window.
   - HYPER vault epoch 30 d (withdrawals take 30 to 60 d).
   - BARD vault epoch 10.5 d with a 3-day veto.
   - Axelar unbonding 7 d (amplifier verifiers 14 d).
   - Polygon 80 checkpoints, about 19 h at the current checkpoint rate.
   - Chainlink 28 d plus a 7-day claim window. UMA 7 d.

---

## 1. Summary table

Stake and value in USD at the prices above. "§1.x" refers to that earlier rule list.

| Bridge / verifier set | Stake (USD) | Slashable for invalid messages? | Value held (USD) | Stake / value | Value moved, 24 h | Deployed limit (deploy note) | Stake withdrawal delay |
|---|---|---|---|---|---|---|---|
| **Axelar** consensus validators (EVM gateways, ITS) | 16.0M: 291.05M AXL bonded. 17 validators with 181.4M AXL ($9.97M) exceed the 60% threshold. | **No.** Double signing 2%, downtime 0.01%. Incorrect votes can only deregister a chain maintainer; the threshold is now 100% of the last 500 polls. | 183.5M (Axelarscan). DefiLlama: 148.4M + 5.8M. | 0.087 (0.054 for the 60% coalition) | 0.46M (Axelarscan) | ITS 6 h net-flow cap per token (opt-in); gateway caps unset on Ethereum (§1.5) | 7 d |
| Axelar amplifier verifiers (10 chains) | 0.077M: 1.40M AXL, 28 verifiers | **No.** No slash function; governance can only jail. | included above | n/a | | same | 14 d |
| **Hyperlane**, HYPER vault on Symbiotic | 1.32M: 19.94M HYPER | **Yes on paper.** Four checkpoint-invalidity types can be attributed on-chain by anyone. Slashes are approved or vetoed by the Foundation and a council. The vault slasher is instant. | 76.5M (DefiLlama) | 0.017 | 1.98M (L2BEAT) | Warp-route token buckets (opt-in, §1.8) | 30 to 60 d |
| Hyperlane EigenLayer AVS | About 1.43M ETH-equivalent of registered weight (about 3.5B), nominal | **No.** Docs: not enabled. | same | n/a | | | 14 d |
| **LayerZero** DVNs | 0 at protocol level. EigenZero: $5M ZRO announced. Ethena Symbiotic vaults: 0. | Default DVNs: **no**. EigenZero: **yes**, with council approval, an 11-day review window and a 10 wETH claim bond. | 11.11B (DefiLlama "LayerZero V2"). The USDT0 adapter alone holds 3.17B on-chain. | 0 (EigenZero over total: 0.00045) | 342.9M (L2BEAT) | OApp RateLimiter (opt-in, §1.4) | EigenLayer 14 d |
| **Wormhole**: 19 guardians, 13 needed | 0 | **No stake** (proof of authority). W staking is for governance only. | 1.648B (Wormholescan). DefiLlama: 1.634B. | 0 | 39.2M (Wormholescan) | Governor: sliding 24 h cap per chain (§1.1) | n/a |
| **Chainlink CCIP**: committee of 9 of 14 to 16 signers, plus RMN | 0 for CCIP. Staking v0.2 (529M, of which 20.4M from operators) covers only the ETH/USD feed. | **No** | 1.454B on-chain (112 Ethereum lock-release pools). DefiLlama: 1.942B. | 0 | 34.1M (L2BEAT) | Token buckets per pool and lane (§1.3) | Staking: 28 d + 7 d |
| CCIP add-on: Lombard LBTC (Symbiotic) | 0.144M BARD, plus 0.0098M LINK | BARD vault: veto slasher, conditions not published. LINK vault: no slasher. | LBTC 632.1M (DefiLlama, burn-and-mint token) | 0.00023 | | LBTC inbound buckets: 407M full, 543M within 1 h (§5) | 10.5 d (BARD), 7 d (LINK) |
| **Across**: optimistic root bundles | Bond 0.45 ABT ($1,099) per bundle. DVM: 19.40M UMA staked ($7.62M). | Proposer bond is forfeited if a dispute succeeds; the DVM decides. | 17.85M LP reserves on-chain. DefiLlama: 18.27M. | 0.00006 (bond); 0.43 (DVM stake) | 34.9M (L2BEAT) | None (§1.6) | Bond back after 30 min; UMA 7 d |
| **Polygon PoS**: 104 validators; checkpoints need more than 2/3 of stake | 342.4M: 3.586B POL. 11 validators with 2.516B POL ($240M) exceed 2/3. | **No.** Slash entry point removed. | 2.184B on-chain (partial). DefiLlama: 2.711B. | 0.16 (0.13 on DefiLlama) | not measured | None (§1.9) | 80 checkpoints, about 19 h |
| **Supra HyperLoop** | Not deployed | n/a | n/a | n/a | | | |
| Symbiosis (Symbiotic SIS vault) | 0.0149M: 853,805 SIS | Veto slasher with 1-day veto; conditions not found | 7.71M (DefiLlama) | 0.0019 | | | 7 d epoch |

---

## 2. Per-bridge facts

### 2.1 Axelar

**Verification.**
- Validators vote on source-chain events. An Ethereum event is confirmed at 3/5 of stake-weighted votes (`voting_threshold` in the EVM module parameters for chain Ethereum, `min_voter_count` 1).
- Outgoing commands are signed with a weighted multisig key. Thresholds: signing 60/100, key generation 80/100 (multisig module parameters).
- 43 validators are bonded; the maximum is 75.
- Sources: LCD `/axelar/evm/v1beta1/params/Ethereum` and `/axelar/multisig/v1beta1/params` (2026-10-16 00:22 UTC; files `data/stake/api/axl_*_refresh.json`); `/cosmos/staking/v1beta1/params` (2026-10-16 00:06 UTC).

**Stake.**
- `bonded_tokens` = 291,051,992.64 AXL (23.1% of the 1,257,464,733 AXL supply). At $0.05496 that is **$16.0M**.
- The largest validator holds 9.9% and the top five hold 27.3%. The 17 largest validators hold 181,375,660 AXL (62.3%, $9.97M), which is enough for 60%.
- Sources: LCD `/cosmos/staking/v1beta1/pool`, `/cosmos/staking/v1beta1/validators?status=BOND_STATUS_BONDED`, `/cosmos/bank/v1beta1/supply/by_denom?denom=uaxl` (2026-10-16).

**Slashing.**
- Parameters (`/cosmos/slashing/v1beta1/params`, 2026-10-16):
  - double-sign fraction 0.02;
  - downtime fraction 0.0001;
  - signed-blocks window 94,426, minimum signed 0.5;
  - downtime jail 7,200 s.
- These are consensus-layer faults, applied automatically by the Cosmos SDK evidence and slashing modules.
- **No rule confiscates stake for votes or signatures on cross-chain messages.**
  - The nexus `EndBlocker` deregisters a chain maintainer whose share of incorrect (or missed) votes in the check window reaches a threshold, and clears its pending rewards for that chain. Code: `x/nexus/abci.go` (copy in `data/stake/code_axelar/x_nexus_abci.go`), comment: "if a chain maintainer has voted incorrectly for too many polls, then it will be de-registered".
  - On-chain parameters (`/axelar/nexus/v1beta1/params`, 2026-10-16): `chain_maintainer_check_window` 500; `chain_maintainer_incorrect_vote_threshold` 100/100; `chain_maintainer_missing_vote_threshold` 100/100.
  - These values were set by governance proposal 256 ("Nexus Params Update", passed, voting ended 2024-11-21), which describes them as preventing "mass de-registration of chain maintainers" (LCD `/cosmos/gov/v1/proposals/256`, 2026-10-16).
  - The documentation still states 5% incorrect or 20% missed in the previous 500 polls: https://docs.axelar.dev/validator/external-chains/overview/ (2026-10-16). The chain parameters prevail.
- Jailed or tombstoned validators are excluded from voting snapshots (`excludeJailedOrTombstoned`, `x/evm/keeper/msg_server.go`).

**Amplifier verifiers.** These serve Flow, Sui, Stellar, XRPL EVM, Plume, Hedera, Berachain, Hyperliquid, Monad and Solana (`axelar-chains-config/info/mainnet.json`, https://github.com/axelarnetwork/axelar-contract-deployments, 2026-10-15).
- Service parameters (CosmWasm query `{"service":{"service_name":"amplifier"}}` to the service registry `[contract address omitted]`, 2026-10-16):
  - minimum bond 50,000 AXL;
  - unbonding 14 days;
  - 5 to 50 verifiers per chain.
- Active verifiers: 18 to 27 per chain, 28 unique. Total bond **1,400,001 AXL ($76.9k)** (`active_verifiers` query per chain, 2026-10-16).
- Voting threshold is 2/3 (VotingVerifier configuration, e.g. Flow).
- The service-registry contract (v1.2.1 code at commit 6703b92) has **no slashing function**. Governance can jail a verifier, and a jailed verifier cannot unbond or claim its stake (`state.rs`, `unbond_verifier`, `claim_verifier_stake`; copy in `data/stake/code_axelar/service_registry/`, 2026-10-15).

**Withdrawal delay.** `unbonding_time` 604,800 s (7 days).

**Value held.**
- Axelarscan `getTVL` (https://api.axelarscan.io/api/getTVL, 2026-10-16; data updated 2026-10-15 21:54 UTC): **$183.5M** over 296 assets, of which ITS assets $133.1M and legacy gateway assets $50.4M.
- The largest single asset is Falcon USD (USDf), $52.6M, locked in an ITS lock/unlock token manager on Ethereum.
- DefiLlama: "Axelar" $148.4M, "Axelar Cross Chain" $5.8M (https://api.llama.fi/protocols, 2026-10-16).
- On-chain check of the Ethereum gateway `[contract address omitted]`: 13,496,372 USDC, 969.9 WETH, 33.0 WBTC, 615,941 USDT, 354,710 DAI and smaller balances, **$19.8M** across the 15 tokens with a balance.

**Value moved.**
- Axelarscan `interchainTotalVolume`: $0.465M in the 24 h to 2026-10-16 00:12 UTC, $23.6M over 30 days (POST https://api.axelarscan.io/api/interchainTotalVolume).
- L2BEAT, last 24 h: Axelar $121.6k (160 transfers), Axelar ITS $9.2k (147 transfers) (https://l2beat.com/interop/protocols/axelar and .../axelar-its, 2026-10-15).

### 2.2 Hyperlane

**Verification.** Default ISMs are validator multisigs (https://docs.hyperlane.xyz/docs/reference/addresses/validators/mainnet-default-ism-validators, 2026-10-16):
- Ethereum: 6 of 9 (Abacus Works, DSRV, Zee Prime, Staked, Luganodes, Mitosis, Substance Labs, Enigma, Citrea).
- Arbitrum: 3 of 5. Base: 3 of 5. Solana: 3 of 4.

**HYPER staking on Symbiotic** (live since 2025-04-22, https://resources.symbiotic.fi/hyperlane-native-staking-powered-by-symbiotic, 2026-10-15).
- On-chain, vault `[contract address omitted]`, collateral HYPER `[contract address omitted]`:
  - `totalStake` **19,940,522 HYPER ($1.32M)**; `activeStake` 19,884,236.
  - HYPER balance of the vault 25,264,582, which includes withdrawals not yet claimed.
  - `epochDuration` 2,592,000 s (30 d).
  - Slasher `TYPE` 0 (instant slasher: no on-chain veto period). Delegator `TYPE` 0.
  - Network limit for the Hyperlane subnetwork 802,666,667 HYPER, so the limit does not bind.
- Docs (https://docs.hyperlane.xyz/docs/protocol-economics/intro, 2026-10-15), paraphrased:
  - If a quorum of validators signs messages that break the protocol's correctness rules (the example is a message absent from the source chain's state), part of the HYPER delegated to that chain can be slashed.
  - Four attributable checkpoint faults are defined in the contract `AttributeCheckpointFraud`: Whitelist (invalid Merkle tree), Premature (signed too early), MessageId (wrong message), Root (wrong root).
  - At launch, the Hyperlane Foundation and a council oversee slashing and can approve or veto each decision. The docs expect a later move to on-chain enforcement.
  - Penalties are spread over all HYPER stakers.
  - Stake is allocated across chains in proportion to their activity, so the stake exposed for one chain is a fraction of the vault.
  - Unstaking takes "roughly one full epoch (~30 to 60 days …)".
- Contract `AttributeCheckpointFraud.sol` (https://github.com/hyperlane-xyz/hyperlane-monorepo/blob/main/solidity/contracts/AttributeCheckpointFraud.sol, 2026-10-15):
  - the four `attribute*` functions have no access restriction;
  - each records the fault type and a timestamp against the recovered signer;
  - the contract itself moves no stake.
- Symbiotic timing rule: a slash must execute within one epoch of its capture time (`executeSlashTimestamp − captureTimestamp ≤ epochDuration`). Requested withdrawals stay slashable until the epoch boundary (https://docs.symbiotic.fi/integrate/networks/slashing and https://docs.symbiotic.fi/modules/vault/introduction/, 2026-10-15).
- Whether any HYPER slash has been executed was not checked.

**EigenLayer AVS.**
- On-chain, `ECDSAStakeRegistry` `[contract address omitted]`:
  - `getLastCheckpointTotalWeight` 109,877.13;
  - threshold 6,667 bps;
  - 13 strategies, each with multiplier 769 bps, except beacon-chain ETH at 772 (sum 10,000).
- If each strategy share is worth about 1 ETH, the registered weight corresponds to about **1.43M ETH ($3.49B)**. Weights update only when operators are refreshed, so this is nominal.
- Docs (https://docs.hyperlane.xyz/docs/protocol/ISM/economic-security/hyperlane-avs.md, 2026-10-15): "Slashing and reward payments are not enabled yet for EigenLayer". The challenger and slasher contracts are "not yet live in production".
- EigenLayer withdrawal delay: `DelegationManager.minWithdrawalDelayBlocks` = 100,800 blocks (14 d).

**Value held and moved.**
- DefiLlama "Hyperlane": $76.5M, of which Ethereum $6.8M (2026-10-16).
- L2BEAT warp routes, last 24 h: $1.98M, 977 transfers, largest $77.3k (https://l2beat.com/interop/protocols/hyperlane-hwr, 2026-10-15).

### 2.3 LayerZero DVNs

**Protocol level.** No stake or bond. Verification is by DVNs, which each OApp chooses.
- L2BEAT describes DVNs as "multisig-like smart contracts"; the default Ethereum DVNs are Canary, Horizen, LayerZero and Nethermind (https://l2beat.com/interop/protocols/layerzero, 2026-10-15).
- LayerZero's metadata API lists 91 DVN contracts on Ethereum under 80 names. One of them, EigenZero (`[contract address omitted]`), is described by its operators as stake-backed (https://metadata.layerzero-api.com/v1/metadata/dvns, 2026-10-16).

**EigenZero.** Launched 2025-11-12, live on Ethereum, BNB Chain and Avalanche.
- Stake: "$5M in slashable ZRO".
- Slashable attestations: those shown to be incorrect after source-chain finality ("e.g., 3 epochs on Ethereum"). Network instability, forks and base-layer faults are excluded, and "Only transactions that have economic impact are slashable".
- Claims: anyone may file a claim at any time by posting a 10 wETH bond. A five-member council (EigenCloud, Chaos Labs, Zellic and others) approves slashing. Affected users are compensated up to their loss. Sources: https://layerzero.network/blog/introducing-eigenzero (2026-10-15); "11-day review window": https://www.eigenlabs.org/blog/eigenzero-layerzero-eigencloud/ (2026-10-15).
- Contract structure (Dedaub audit of the LayerZero DVN AVS, 2025-05-13: https://dedaub.com/audits/layerzero/layerzero-dvn-avs-may-13-2025/, 2026-10-15):
  - anyone can queue a slashing request with a bond;
  - only the council can accept a request, and it decides whether the bond is refunded;
  - execution goes through EigenLayer's `AllocationManager.slashOperator`.
- **On-chain check.** The EigenLayer factory strategy for ZRO (`StrategyFactory.deployedStrategies(ZRO)` = `[contract address omitted]`) holds 10,701 ZRO ($22.4k). The announced stake is not there, and its location was not found.
- EigenLayer delays read on-chain: `AllocationManager.DEALLOCATION_DELAY` = 100,800 blocks (14 d); `ALLOCATION_CONFIGURATION_DELAY` = 126,000 blocks (17.5 d). Deallocated stake therefore stays slashable for 14 d, which covers the 11-day review window.

**Ethena (Symbiotic).** Vaults rsENA `[contract address omitted]` and rsUSDe `[contract address omitted]`. Their metadata says they were set up to back LayerZero DVNs for USDe transfers (https://github.com/symbioticfi/metadata-mainnet, 2026-10-15).
- On-chain both have `totalStake` = 0.
- Both use veto slashers with a 3-day veto, 7-day epochs, and no slash requests.

**Value held.**
- DefiLlama "LayerZero V2" (Bridge): **$11.11B**, of which Ethereum $6.88B. "USDT0" is listed separately at $3.17B; whether "LayerZero V2" also counts it was not checked. "Stargate V2": $78.4M.
- On-chain checks:
  - USDT0 OAdapter `[contract address omitted]` holds 3,170,047,111 USDT.
  - Stargate v2 pools hold 40.50M USDC, 2.77M USDT and 4,143.7 ETH ($10.1M).

**Value moved.** L2BEAT, last 24 h: $342.94M, 6.65k transfers, largest $18.98M (2026-10-15).

### 2.4 Wormhole

**Verification and stake.** 19 guardians; "A quorum of 13 signatures is required to produce a valid VAA".
- The docs describe a "purpose-built Proof-of-Authority (PoA) consensus model": "Wormhole relies on a network of established validator companies instead of token-based incentives". They call proof of stake "not well-suited" for this design (https://wormhole.com/docs/protocol/infrastructure/guardians/, 2026-10-15).
- W staking (live 2024-06-06) delegates governance voting power: "By staking your W tokens, you delegate your voting power"; "There is no token lockup when staking for governance". The page says nothing about guardians or slashing (https://wormhole.com/blog/stake-for-governance-is-now-live-for-w-token-holders, 2026-10-16).
- **No stake backs guardian signatures.**

**Value held.**
- Wormholescan scorecards: `tvl` **$1,648.4M** (https://api.wormholescan.io/api/v1/scorecards, 2026-10-15 23:56 UTC).
- DefiLlama "Portal": $1,634.0M, of which Ethereum $1,387.2M, Algorand $109.3M, BSC $64.0M, Solana $52.3M (https://api.llama.fi/protocol/portal, 2026-10-16).
- On-chain check of the Ethereum Token Bridge `[contract address omitted]` (address from `sdk/mainnet_consts.go` in the Wormhole repository): 47,837.5 WETH, 2,548.5 WBTC, 8.27M USDC, 3.81M USDT and smaller balances, **$340.2M** for the 20 tokens checked.
  - The rest of DefiLlama's Ethereum figure sits in tokens outside that list; this was not resolved.

**Value moved.** Wormholescan: $39.2M (24 h), $1.46B (30 d), $18.2B (1 y).

**Limit.** The Governor (§1.1). Caps in force (`results/wormhole_envelopes.md`):
- Solana 20; Ethereum 10;
- Arbitrum, Base and Sui 2.5 each;
- BSC, Polygon, Avalanche, Aptos and Optimism 1 each;
- total **$42.5M per sliding 24 h** (all in $M).

The guardians apply the Governor at signing.

### 2.5 Chainlink CCIP

**Verification.**
- CCIP v2.0 uses a CommitteeVerifier: 9 signatures per source chain, from 14 to 16 signers (65 source-chain configurations as of 2026-09-28). The v1.6 OCR signer set is "equivalent to a 6/16 multisig on Ethereum" (https://l2beat.com/interop/protocols/ccip, 2026-10-15).
- The CCIP docs name 16 node operators for the Committee Verifier (https://docs.chain.link/ccip/concepts/architecture/offchain/risk-management-network, 2026-10-16).

**Risk Management Network (RMN).**
- Docs (same page): the RMN is a manual on-chain flag set through the RMN contract, holding a registry of cursed chains or lanes; "When a chain or lane is cursed, sends and executions involving it revert until the curse is lifted".
- L2BEAT (2026-10-15):
  - on Ethereum the RMN 2.1 contract has been curse-only since 2026-08-12 (`isBlessed()` returns true);
  - a zero-delay timelock and, since 2026-09-28, a single externally owned address may impose curses but not lift them.
- No stake or bond for RMN operators appears in the Chainlink posts or the L2BEAT profile read.

**Chainlink Staking v0.2.** On-chain reads, Ethereum:

| Pool | Contract | `typeAndVersion` | Principal | Cap | Per-staker limits |
|---|---|---|---|---|---|
| Community | `[contract address omitted]` | CommunityStakingPool 1.0.0 | **40,875,000 LINK** | 40,875,000 LINK | 1 to 15,000 LINK |
| Operator | `[contract address omitted]` | OperatorStakingPool 1.0.0 | **1,641,898.67 LINK** | 4,125,000 LINK | 1,000 to 75,000 LINK |

- `getUnbondingParams` for both pools: 2,419,200 s (28 d) and 604,800 s (7-day claim window).
- `PriceFeedAlertsController 1.0.0` (`[contract address omitted]`), `getFeedConfig(ETH/USD proxy)` returns (10,800 s; 12,000 s; 700 LINK; 7,000 LINK). My reading of the field order: priority-period alert threshold, open alert threshold, slash per node operator, alerter reward.
- Blog (https://chain.link/blog/chainlink-staking-v0-2-overview, published 2023-08-25, updated 2023-11-21, read 2026-10-15):
  - node operators serving the ETH/USD feed are slashed 700 LINK each "if a valid alerting condition is met";
  - "Community Stakers will not be at risk of slashing";
  - future upgrades may extend staking to further oracle services, with CCIP named as an example, stated as a possibility.
- **No staked LINK is slashable for CCIP messages.** Value: community $509.0M, operators $20.4M, total $529.4M.

**Value held.**
- `tokens.json` in the Chainlink docs repository (snapshot of 2026-10-14, in `data/ccip/lanes_current/`) lists 112 Ethereum pools that hold tokens (lock-release, siloed lock-release, USDC).
- Their on-chain balances, priced, sum to **$1,454.3M**. Fifteen non-zero balances without a DefiLlama price are excluded.
- DefiLlama "CCIP": $1,941.9M, of which Ethereum $1,498.8M.

**Value moved.** L2BEAT, last 24 h: $34.08M, 886 transfers, largest $4.19M.

**Add-on stake through Symbiotic.** See §3 (Lombard, Solv).

### 2.6 Across

**Settlement.**
- Root bundles (relayer refunds and pool rebalances) are proposed to HubPool `[contract address omitted]`. On-chain:
  - `bondAmount` **0.45** of `bondToken` ABT ("Across Bond Token", `[contract address omitted]`);
  - `liveness` **1,800 s**;
  - `identifier` "ACROSS-V2".
  - The current proposal has one proposer address.
- L2BEAT: ABT is an ETH wrapper usable as a bond only by permissioned proposers; one proposer address is listed; "UMA is not involved in this happy path" (https://l2beat.com/interop/protocols/across, 2026-10-15).
- Docs (https://docs.across.to/introduction/security/disputing-root-bundles, 2026-10-16):
  - "Anyone can dispute a root bundle proposal if they believe it is invalid", posting a bond of about 0.45 ABT;
  - "UMA token holders vote on whether the proposal was valid per UMIP-157 / UMIP-179 rules";
  - the losing side's bond goes to the other side.
- UMA `Store.computeFinalFee(ABT)` = 0.055 ABT.

**UMA DVM** (implementation of "Oracle" in the UMA Finder `[contract address omitted]` = VotingV2 `[contract address omitted]`). On-chain:
- `cumulativeStake` **19,396,849 UMA ($7.62M)**, which is 14.7% of the 131.53M supply;
- `gat` 5,000,000 UMA; `spat` 0.65;
- vote phase 86,400 s (commit, then reveal);
- `unstakeCoolDown` 604,800 s (7 d).

**Value held.** LP reserves are liquid plus utilized reserves from `pooledTokens`: **$17.85M**.
- By token: WBTC $9.62M (117.3 WBTC), WETH $5.01M (2,053 WETH), USDT $1.22M, USDC $1.00M, ACX $0.93M, DAI $0.06M.
- The liquid part sitting in HubPool is $8.77M.
- DefiLlama "Across": $18.27M. Spoke-pool balances on other chains were not read.

**Value moved.** L2BEAT, last 24 h: $34.90M, 27.92k transfers, largest $729.9k.

### 2.7 Polygon PoS bridge

**Checkpoints.** "State updates are settled on Ethereum if signed by at least 2/3+1 of the Polygon PoS validators stake". The contracts "do not check whether the state transitions are valid" (https://l2beat.com/scaling/projects/polygon-pos, 2026-10-15).

**Stake.** On-chain, StakeManager proxy `[contract address omitted]`:
- `currentValidatorSetTotalStake` **3,585,788,020 POL ($342.4M)**;
- `currentValidatorSetSize` 104; `validatorThreshold` 105; `minDeposit` 100,000 POL.
- `validators(i)` for i = 1..209: the active set holds 3,607.3M POL, of which self-stake 10.7M and delegated 3,596.5M.
- The largest validator holds 11.7%. The 11 largest hold 2,516.0M POL ($240.2M), which exceeds 2/3.

**Slashing: none.**
- The implementation behind the proxy (`implementation()` = `[contract address omitted]`) contains neither the `slash(bytes)` selector `0x5e47655f` nor `unjail(uint256)` `0x178c2c83` (bytecode search).
- The public repository removed the "slashing entry point and validator unjailing" on 2026-08-06 (commit aa960e3, https://github.com/0xPolygon/pos-contracts; `StakeManager.sol` on `main` has no occurrence of "slash", read 2026-10-15).
- L2BEAT's update of 2024-09-05: "`slash()` now just always reverts".

**Withdrawal delay.**
- `withdrawalDelay` = 80 (checkpoint epochs; `currentEpoch` 114,218 tracks the checkpoint count).
- The last 40 checkpoints on RootChain `[contract address omitted]` (`headerBlocks`) were 855.6 s apart on average, so 80 checkpoints are about **19.0 h**.

**Value held.** On-chain, 30 major tokens plus ETH:

| Escrow | Value | Main holdings |
|---|---|---|
| ERC20Predicate `[contract address omitted]` | $1,668.3M | 1,006.2M USDC, 443.7M DAI, 1,922.8 WBTC, 5,682.5 wstETH, 1.14M LINK |
| DepositManager `[contract address omitted]` | $293.9M | 3,077.4M POL |
| EtherPredicate `[contract address omitted]` | $221.1M | 90,573.4 ETH |
| `[contract address omitted]` | $0.26M | |
| **Total** | **$2,183.6M** | |

- DefiLlama "Polygon Bridge": $2,711.3M.
- L2BEAT TVS (its total-value metric): $3.85B, of which canonically bridged $2.31B.

**Other control.** L2BEAT: a 5-of-9 multisig "Can arbitrarily moves tokens out of the ERC20 escrow without a contract upgrade", and upgrades have no delay.

### 2.8 Supra HyperLoop

**Not deployed.**
- The SupraNova roadmap lists HyperLoop under "Upcoming releases", described as a fast multisig bridge with rotating validator sets whose correctness rests on an equilibrium argument (https://docs.supra.com/supranova/future-roadmap, page "Last updated on September 24, 2026", read 2026-10-15).
- The model and stake conditions in the HyperLoop paper are covered in `results/positioning_stock_flow_governor.md` §1.2.

**The live Supra bridge is SupraNova (HyperNova).**
- Ethereum to Supra: verified with Ethereum sync-committee signatures ("more than 90%").
- Supra to Ethereum: verified with Supra committee threshold signatures. The docs describe no bridge-specific stake or slashing; they note that collusion of the Supra committee would already be a consensus failure of the Supra chain itself (https://docs.supra.com/supranova/security, 2026-10-15).
- A 9-of-16 multisig sets per-transfer and per-token vault caps and can pause (https://docs.supra.com/supranova/supranova-bridge-admin-functionalities, 2026-10-15).
- The reverse direction went live around 2026-08-21 (https://globalcrypto.tv/supranova-reverse-bridge-goes-live-linking-supra-and-ethereum/, 2026-10-15).
- DefiLlama "Supra Bridge" TVL is about $0, so it appears untracked.

---

## 3. Bridge arrangements backed by restaking (EigenLayer, Symbiotic)

**How this list was built.**
- Symbiotic: all 21 networks and 164 vaults in `symbioticfi/metadata-mainnet` (https://github.com/symbioticfi/metadata-mainnet, tree read 2026-10-15 23:51 UTC); bridge-related entries were filtered and every vault was read on-chain.
- EigenLayer: the AVSs named in bridge documentation (Hyperlane, LayerZero DVN AVS / EigenZero). Other EigenLayer AVSs were not enumerated.

| Arrangement | Layer | Collateral | Stake at block 26,201,369 | Slasher | Veto | Epoch / delay | Conditions published? | Who decides |
|---|---|---|---|---|---|---|---|---|
| Hyperlane HYPER vault | Symbiotic | HYPER | 19.94M ($1.32M) | Instant (type 0) | None on-chain | 30 d | **Yes** (four checkpoint types) | Foundation and council approve or veto |
| Hyperlane AVS | EigenLayer | ETH and LSTs | About 1.43M ETH-eq. weight (nominal) | Not enabled | n/a | 14 d withdrawal | No (not enabled) | n/a |
| EigenZero (LayerZero DVN) | EigenLayer | ZRO | $5M announced; not located on-chain | Via council-accepted requests | 11-day review | 14 d deallocation | **Yes** (finality, economic impact, exclusions) | Five-member council; claimant posts a 10 wETH bond |
| Lombard CCIP network (LBTC) | Symbiotic | BARD | 1,291,037 BARD ($144k); network limit 20M BARD | Veto (type 1) | 3 d | 10.5 d | No | Not stated |
| Lombard and Solv CCIP networks | Symbiotic | LINK | 790.4 LINK ($9.8k) | **None** (slasher address zero) | n/a | 7 d | No | n/a |
| Solv CCIP network (SolvBTC) | Symbiotic | SOLV (OFT) | 0 | Veto | 3 d | 10.5 d | No | Not stated |
| Ethena rsENA / rsUSDe (LayerZero DVN) | Symbiotic | ENA / sUSDe | 0 / 0 | Veto | 3 d | 7 d | No | Not stated |
| Symbiosis | Symbiotic | SIS | 853,805 SIS ($14.9k); network limit 1M SIS | Veto | 1 d | 7 d | Not found | Not stated |
| Cycle Network | Symbiotic | CYC (OFT) | 0; network limit 0 | Veto | 3 d | 7 d | No | Not stated |

Notes on this table:
- No slash request has ever been made on any veto slasher listed (`slashRequestsLength` = 0).
- Lombard's announcement (https://www.lombard.finance/blog/lombard-chainlink-and-symbiotic-launch-first-of-its-kind-cryptoeconomic-guarantee-layer-for-cross-chain-lbtc-transfers/, dated 2025-09-15, read 2026-10-15) gives no slashing conditions. Neither does Symbiotic's Solv post (https://resources.symbiotic.fi/symbiotic-solv-protocol-and-chainlink-collaborate-to-enhance-cryptoeconomic-guarantees-of-cross-chain-solvbtc-transfers-via-ccip, dated 2025-10-30, read 2026-10-15); it describes "a Symbiotic-powered monitoring network that monitors SolvBTC transfers via CCIP and issues alerts".
- Symbiotic veto rule: `requestSlashTimestamp + vetoDuration − captureTimestamp ≤ epochDuration`. For BARD this means a request must come within 7.5 days of the capture time.

---

## 4. What the stake would have to cover

These ratios use the stock (value held). Section 5 uses flow quantities.

| Bridge | Stake slashable for invalid messages (USD) | Value held (USD) | Ratio |
|---|---|---|---|
| Hyperlane (HYPER) | 1.32M (whole vault; a single chain's share is smaller) | 76.5M | 0.017 |
| EigenZero | 5M announced | Only OApps that select it; not measured | n/a |
| Lombard add-on | 0.144M (conditions unpublished) | LBTC 632.1M | 0.00023 |
| Across bond | 0.0011M per bundle (forfeited on a successful dispute) | 17.85M | 0.00006 |
| All others in scope | 0 | | 0 |

Stake that exists but is not slashable for invalid messages:

| Bridge | Stake (USD) | Value held (USD) | Ratio |
|---|---|---|---|
| Polygon | 342.4M | 2,183.6M | 0.16 |
| Axelar | 16.0M | 183.5M | 0.087 |
| Chainlink Staking | 529.4M | CCIP value not covered | n/a |
| Hyperlane AVS | about 3.5B nominal | 76.5M | not slashable |

---

## 5. Stake against flow quantities from deployed limits

**LBTC on CCIP** (stake: BARD $144k; the LINK vault has no slasher).
- Source: `lanes.json` of 2026-10-14 (`data/ccip/lanes_current/`), read as in `ccip/ccip_flows_template.md` §2.
  - For a message with no source-chain event, the destination pool's inbound bucket applies.
  - The source pool's outbound bucket is not consumed.
- LBTC has 103 enabled inbound buckets (LombardTokenPool 2.1.0 on 11 EVM chains, plus Solana). Most are 50 LBTC with refill 0.00462963 LBTC/s, so each refills in 3 h.
- Sum over buckets: b = 4,950.12 LBTC, r = 0.458333 LBTC/s. β(d) = b + r·d:

| d | β(d) | USD | BARD stake / β(d) |
|---|---|---|---|
| 0 (full buckets) | 4,950 LBTC | $407.3M | 0.035% |
| 1 h | 6,600 LBTC | $543.0M | 0.027% |
| 24 h | 44,550 LBTC | $3.67B (above LBTC's $632M TVL) | |

- LBTC is burn-and-mint on every CCIP chain. A release on an invalid message is a mint without backing, not a draw on an escrow.
- A search-engine summary of a third-party page (https://yellow.com/vi/asset/bard, page not opened) says LombardTokenPool mints only after a separate Lombard authorization. This is unverified. If it holds, the CCIP verifiers alone cannot trigger these flows.

**SolvBTC on CCIP** (stake: 0).
- 124 inbound entries, many at the lockdown setting (2 base units).
- b = 143.40 SolvBTC, r = 0.0055901 SolvBTC/s.
- β(0) = $11.7M; β(1 h) = $13.4M; β(24 h) = $51.2M; against DefiLlama "SolvBTC" $522.9M.

**Wormhole** (stake: 0).
- Governor caps total $42.5M per sliding 24 h over the ten chains in `results/wormhole_envelopes.md`, against $1.648B held.
- The guardians apply the Governor at signing. A 13-of-19 quorum can therefore release queued transfers or sign around it, so the cap bounds failures upstream of signing, not a signing quorum (positioning note, `results/positioning_stock_flow_governor.md`).

**Bridges in scope with stake but no protocol-level limit** (Polygon; Axelar gateway on Ethereum; Across). The flow quantity equals the stock.
- Hyperlane and LayerZero limits, and Axelar ITS limits, are opt-in per route or token (§1.4, §1.5, §1.8). The aggregate flow quantity for those protocols would need a per-route crawl, which was not done.

---

## 6. Method and reproducibility

**Scripts** (in `research_ideas/probes/bridge_limits/stake/`; they use `../ethcall_lib.py`):
- `stake_reads.py`: Ethereum reads at a pinned block.
- `value_calc.py`: prices, extra reads, valuation.
- `polygon_validators.py`
- `axelar_reads.py`: LCD queries and Axelarscan.

Run them with the Python environment of requirements.txt.

**Raw outputs** (under `data/stake/`, untracked):
- `onchain/eth_reads_20261016T000421Z.json` and `eth_calllog_20261016T000421Z.json`: every call with RPC, block, calldata and raw return.
- `onchain/extra_calllog_*.json`, `onchain/polygon_validators_*.json`, `onchain/valuation_20261016T000856Z.json`.
- `api/axelar_reads_20261016T000617Z.json`, `api/axelarscan_getTVL_refresh.json`, `api/llama_*refresh*.json`, `api/coingecko_simple_price_refresh.json`, `api/wormholescan_scorecards.json`, `api/lz_metadata_dvns_refresh.json`.
- `symbiotic/` (metadata).
- `code_axelar/`, `code_polygon/` (source copies).

**Calls.** Selectors are Keccak-256 of the signature; arguments and returns are ABI-decoded by hand.
- Across HubPool: `bondAmount()`, `bondToken()`, `liveness()`, `identifier()`, `finder()`, `rootBundleProposal()`, `pooledTokens(address)`.
- UMA Finder: `getImplementationAddress(bytes32)` for "Oracle" and "Store".
- UMA VotingV2: `cumulativeStake()`, `gat()`, `spat()`, `unstakeCoolDown()`, `voteTiming()`.
- UMA Store: `computeFinalFee(address)`.
- Polygon StakeManager: `currentValidatorSetTotalStake()`, `currentValidatorSetSize()`, `withdrawalDelay()`, `currentEpoch()`, `minDeposit()`, `validators(uint256)`, `implementation()`. Then `eth_getCode` on the implementation and a selector search.
- Polygon RootChain: `currentHeaderBlock()`, `headerBlocks(uint256)`.
- Chainlink pools: `typeAndVersion()`, `getTotalPrincipal()`, `getMaxPoolSize()`, `getUnbondingParams()`, `getStakerLimits()`.
- Chainlink alerts controller: `getFeedConfig([contract address omitted])`.
- Hyperlane ECDSAStakeRegistry: `getLastCheckpointTotalWeight()`, `getLastCheckpointThresholdWeight()`, `quorum()`.
- Symbiotic vaults: `collateral()`, `totalStake()`, `activeStake()`, `epochDuration()`, `slasher()`, `delegator()`, `burner()`.
- Symbiotic slashers: `TYPE()`, `vetoDuration()`, `resolverSetEpochsDelay()`, `slashRequestsLength()`.
- Symbiotic delegators: `TYPE()`, `networkLimit(bytes32)`, `maxNetworkLimit(bytes32)`, with subnetwork = network address followed by identifier 0.
- EigenLayer: `DelegationManager.minWithdrawalDelayBlocks()` at `[contract address omitted]`; `AllocationManager.DEALLOCATION_DELAY()` and `ALLOCATION_CONFIGURATION_DELAY()` at `[contract address omitted]`; `StrategyFactory.deployedStrategies(ZRO)` at `[contract address omitted]`.
- ERC-20 `balanceOf` for escrow balances, and `eth_getBalance` for ETH.

**Axelar** (Cosmos REST):
- `/cosmos/staking/v1beta1/pool`, `/params` and `/validators?status=BOND_STATUS_BONDED`;
- `/cosmos/slashing/v1beta1/params`;
- `/cosmos/bank/v1beta1/supply/by_denom`;
- CosmWasm smart queries `service` and `active_verifiers` (base64 JSON) to the service registry.

**Value aggregates.**
- DefiLlama `https://api.llama.fi/protocols` and `/protocol/portal`.
- Wormholescan `/api/v1/scorecards`.
- Axelarscan `getTVL` and `interchainTotalVolume`.
- L2BEAT interop pages (24 h snapshots at access).

---

## 7. Gaps and caveats

- **EigenZero's stake** was not located on-chain. The $5M is the launch figure (USD at 2025-11). The factory ZRO strategy holds only 10,701 ZRO.
- **Hyperlane AVS weight** is converted to ETH by assuming one ETH per strategy share; registry weights refresh only on operator updates.
- **Per-chain HYPER allocation** was not read. The stake exposed for one chain's messages is a fraction of the $1.32M.
- **Value-held figures are stocks at one block and use market prices.** Polygon and Wormhole on-chain sums cover the listed tokens only. CCIP excludes 15 unpriced balances and chains other than Ethereum. Across excludes spoke pools.
- **Burn-and-mint tokens** (LBTC, SolvBTC, ITS mint/burn tokens) have no escrow stock. For them, a release on an invalid message is unbacked supply, and §5 measures it by limits rather than by value held.
- **Chainlink alert fields** are named by my reading of the getter's order.
- **Slashing executions.** Whether any slash was ever executed for HYPER (an instant slasher has no request counter) was not checked.
- **Not covered:** other bonded designs outside the requested list, such as THORChain node bonds, Chainflip and Gravity Bridge, were not examined. Other EigenLayer AVSs that may verify cross-chain messages, such as Lagrange and Omni, were not enumerated.
