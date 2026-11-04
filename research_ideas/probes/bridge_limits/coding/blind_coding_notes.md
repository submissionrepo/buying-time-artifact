# Blind coding notes

Coded on 2026-10-16 from `codebook.md`, `blind_input.csv` and public sources only. No other repository
file was opened or searched. The session's automatic context did show recent commit titles of the
repository, one of which quotes a per-leg verifier share from earlier work; that figure was not used.
X posts were read through a public read-only mirror; block times and contract state were read from
public RPC endpoints and block explorers.

Result: 26 CHECK (20 receiving_contract, 6 offchain_verifier), 20 KEYS, 6 OTHER, 5 EVENT;
3 rows with low confidence (E25, E61, E69), 12 medium.

## How the fields were read

- **class**: the stage where the unbacked release entered. When a minted claim was later redeemed,
  the class follows the first failure (as for E11).
- **legs**: bridge releases only. Borrowing against minted claims (E10), swaps into an exchange pool
  (E65, alloyed-BTC pool), and sales of minted tokens (E11, E39) are realization, not legs.
  Releases from a pre-allocated supply (E16 hub, E31 Neo N3, E50 NEVM vault, E21 non-Ethereum
  chains) are coded `mint`: they add unbacked circulating supply and deplete no other user's
  backing. A literal reading of "pays from an escrow" would code them `escrow`. Relayer and solver
  inventory is `other` (E40, E56). Unknown shares are written `unknown`.
- **Shares above 1**: E11 (mint 1.0, redemption 0.78), E31 (mint 1.0, redemptions 0.84 and 0.04),
  E50 (NEVM release 1.0, UTXO issuance 1.0), E51 (mint 1.0, redemption 1.0).
- **legs_through_verifiers**: `yes` when the release rested on an attestation by the verifier layer
  (signing set, relayer, sequencer, or a light client verifying a real packet), so a limit in that
  layer would have counted it. `no` when the release bypassed the verifiers, when taken keys were
  used outside their software, or when the verifiers had signed a different object that the
  receiving side reinterpreted (E58: a signature for a 3,097 NIGHT release; E60: export data carried
  inside a notarized block; E50 NEVM leg: a burn of a custom asset read as SYS).
- **release_point_contract**: contract custody is `yes` even when the contract is immutable (E52,
  E53); there a limit would have had to be in the deployed code. In-protocol transfer paths whose
  credit is a consensus rule (E61, E62) are `unknown`.
- **pause_holder**: `independent_of_failure` when a party whose keys were not taken could stop
  further releases by a means that does not run through the failing logic (a contract pause, a
  watcher or guardian action, validators or the operator halting their own nodes). Flaws in an
  operator's own off-chain software (E03, E04, E06, E46, E56) are coded independent because the
  operator could stop that software; a stricter reading of "whose code was not the failing code"
  would change these five. `controlled_by_failing_party` when the pause or configuration authority
  sat with the taken keys. `no_pause_function` when custody sat at the taken key or the contract has
  no pause.
- **first_response_type**: a dated on-chain pause, halt or chain stop is compared with the first
  operator statement; whichever is earlier is coded. Third-party alerts are coded only when no
  operator response is documented.

## Hard cases

- **E05 Poly Network 2021 (CHECK, medium).** Releases were signed with a keeper key the initiating
  party installed, so they carried authorizations that look valid, which reads like KEYS. Coded CHECK
  because the key set was replaced through a call the receiving manager should have refused; no
  existing key was obtained (Mudit Gupta's analysis). The releases did not pass the original
  verifier set.
- **E25 Orbit Bridge (KEYS, low).** The row says validators signed withdrawals that reused nonces of
  earlier deposits and that the operator states no key was taken. The sources I could open report
  seven of ten signer signatures, an initial view that signer keys were in outside hands, the
  developer's later legal action over a firewall change by a former officer, and replay only as
  speculation. If the operator's account holds (its own signing software produced the signatures
  with no outside access), the row is CHECK / offchain_verifier with legs through the verifiers;
  hence `unknown` for legs_through_verifiers.
- **E55 Taiko (KEYS, medium).** Two flaws combined: the enclave signing key was published in a
  public repository, and the attestation contract accepted a debug enclave, from which the
  instance key was read. Coded KEYS because the instance key that signed the proofs was obtained
  through these flaws. CHECK / receiving_contract is the alternative.
- **E64 Liquid (EVENT, high).** The row's wording ("unbacked mint ... on the sidechain",
  "proof-verification cache flaw") can be read as a peg-in check failure. The operator assessment
  places the cache flaw in rangeproof verification of an ordinary sidechain transaction, with no
  peg-in and no key taken; the federation then signed a valid peg-out of those L-BTC. Only the
  Bitcoin leg is listed, since the sidechain inflation was not a bridge release.
- **E49 Gravity Bridge (EVENT, medium).** The fabricated mapping entered through the chain's
  handling of a token-deployment claim from Ethereum (a missing collision check), which could be
  coded CHECK in the chain module. Coded EVENT because the release leg (Gravity chain to Ethereum)
  was a send of valueless tokens that the sending chain recorded as vouchers for escrowed tokens,
  honored by validators with intact keys.
- **E52 Aztec Connect (CHECK, medium).** One L1 contract is both the deposit and the release
  contract. The unbacked balance came from a deposit row the proof accepted but settlement never
  collected, which is also a record that moved no value (EVENT). Coded CHECK because the missing
  check, that proof side effects equal processed side effects, sits in the receiving contract.
- **E56 Across (CHECK / offchain_verifier, medium).** The loss fell on one relayer's own capital,
  close to the codebook's OTHER case for a liquidity provider's own key. No key was involved; the
  relayer's event reader accepted forged deposit payloads, which matches CHECK.
- **E46 TAC (CHECK / offchain_verifier, high).** The row's "origin-side deposit flow accepted a
  deposit notice" suggests EVENT. The post-mortem names the sequencer software, which did not check
  the minter code of the sending token wallet, as the failing check.
- **E32 FEG (CHECK / receiving_contract, medium).** The row calls the failing component "the bridge
  relayer"; CertiK's analysis (of decompiled code) identifies it as an on-chain relayer contract on
  each receiving chain. The messages were real Wormhole messages from the initiating party's
  contract, so the legs are coded as passing the verifiers.
- **E67 Payy (CHECK / receiving_contract, medium).** The invalid burn proof arrived in batches
  posted by the operator's usual posting address, so the legs pass the operator's sequencer and
  prover. The operator's report did not render; secondary summaries place the flawed verifier
  on chain.
- **E61 Oraichain and E69 NEAR Intents (OTHER, low).** Both operators named a component (an EVM
  cross-chain transfer path; the interaction of the deposit and withdrawal infrastructure with the
  intents contract) without publishing the flaw. E69's "contract-side fix plus infrastructure fixes"
  leans toward EVENT or CHECK / offchain_verifier.
- **E27 SaitaChain (OTHER, medium).** A listing function let any caller become a token's lister and
  withdraw the custody balance. No cross-chain message or key was involved.
- **E22 Multichain (KEYS, medium).** Who used the MPC keys is not established. The Fantom bridge
  custody on Ethereum is an externally owned address (checked on chain), so the release point is
  `no` and the pause holder `no_pause_function`.
- **E47 THORChain 2026.** pause_holder `no_pause_function`: the protocol halted signing and trading
  within about 52 minutes, but the reconstructed key signed transfers directly and router token
  releases continued after the halt. first_response stays `onchain_pause` because the halt is the
  first dated response. release_point_contract `yes` because the Ethereum leg (all tokens, per
  QuillAudits) left the router contract; about 41% of value (UTXO chains) sat at the key itself.
- **E14 Harmony 2022.** first_response `onchain_pause`: the remaining owners raised the Ethereum
  multisig threshold from 2 to 4 at 19:53 UTC, before the 23:13 UTC operator post. If a threshold
  change does not count as a halt, the code is `operator_post`.
- **E64 first response.** The bridge nodes were halted at 18:26 UTC (operator assessment), before
  the on-chain message (19:31) and the post (20:25). The time comes from the operator, not from a
  transaction.
- **E31 Poly Network Neo N3 route.** first_response `third_party`: the only dated response is a
  post by the main application on the route; the bridge operator made no statement.
- **E38 Seedify (legs).** The BSC leg is coded `escrow` by inference (BSC is the token's home chain,
  where a LayerZero adapter would release locked tokens); no source states it. Whether the Avalanche
  mint went through counterfeit-peer messages or a direct mint is not stated, so that leg is
  `unknown` for the verifiers.
- **E12 Meter (legs).** Sources name minted BNB and WETH representations on the Moonriver side and
  emptied BNB and WETH reserves (1,391 ETH and 2.74 BTC by CertiK's count) without a per-leg split.
- **E44 Hyperbridge (shares).** Against the revised 2.5M total: an escrow release of about 245 ETH
  (about 561K, 0.22; chain not named, ETH-denominated) and sales of minted tokens of about 237K
  (0.09). The remaining 0.69 (Base, Arbitrum, BNB Chain, DOT-denominated) is not attributed in the
  sources read.
- **E42 IoTeX.** The CIOTX mints are a second leg with unknown share; the 4.4M headline counts the
  reserve only.
- **pause_holder unknown**: E24, E34, E35, E58, E59. No source names a pause holder or shows
  whether one existed. E58's treasury released a further 14,113 NIGHT after the bridge was
  reported offline (row note).

## Input statements that the sources did not support, and conflicts among sources

1. **E25**: "six withdrawals that reused nonces" and "the operator states that no keys were taken
   and that the contract worked as designed" are not in the sources I could open. Rekt News lists
   five named withdrawals and treats replay as speculation; the operator's X post mentions only an
   unidentified access at 20:52:47 UTC. The Korean statement on Medium returned an access error.
2. **E24**: the row's "valid two-operator confirmations"; CertiK names a single operator wallet as
   the only caller of the release function.
3. **E51**: Common Prefix dates the Axelar emergency committee pause at 20:45 on June 17; the row
   gives an on-chain deactivation at 2026-06-18 17:47:53 UTC. These may be two steps.
4. **E50**: the row's Halborn source describes 5B SYS minted on the UTXO side against a burn that did
   not exist; the operator post-mortem (also a row source) describes the NEVM vault manager releasing
   native SYS against a real burn of a custom asset. The row follows the post-mortem.
5. **E44**: the row's "about 1 billion bridged DOT"; Verichains lists DOT mints of about 1.72M plus
   about 1B ARGN, 211K MANTA and 23B CERE, and describes Ethereum only, while Decrypt (citing the
   operator) names four chains.
6. **E47**: the operator report lists manual halt blocks (trading halt at 26,183,438) below the
   solvency-halt block given by QuillAudits (26,190,429), which conflicts with the order
   "automatic halt first". The 52-minute figure is the operator's.
7. **E64**: the row's "unbacked mint" and "proof-verification cache" wording against the
   post-mortem's ordinary-transaction rangeproof cache with no peg-in (not wrong, but it invites a
   CHECK coding).
8. **E46**: the row cites press for disclosure on 2026-05-11; the earliest operator X post found is
   2026-05-13 17:52 UTC and refers to an earlier announcement. The post-mortem's BLUM figures differ
   internally (117M and 302M).
9. **E32**: the row's "bridge relayer" names an on-chain contract, not off-chain software.

Checked and consistent: E35 exit mode at 13:13:35 and false exits at 14:22:47 UTC (on chain; the
Blockaid narrative orders them loosely and Verichains gives the year as 2024); E14 four owners and
threshold 2, then 4 (on chain; Rekt News says 2-of-5); E13 pause at 15:24:40 UTC; E16 last block
before the halt at 22:13:14 UTC; E21 Ethereum pause at 01:35:35 UTC; E27 maintenance mode at
10:58:35 UTC; E30 pause at 10:15:23 UTC; E50 release at 08:19:43 and pause at 19:23 to 19:26 UTC;
E55 vault pause at 05:40:11 UTC on June 22, after the 00:44 UTC operator post; E63 BTC release at
17:32:18 UTC, 22 minutes before the trading halt; E65 mint at 21:50:08 UTC on June 25 and the
Osmosis action at 19:35:16 UTC on September 7.

## Sources that could not be read

Medium pages (Poly Network 2023 analysis, Orbit statement, Qubit, Harmony 2022, Nomad, Flamingo)
returned access errors; the Payy post-mortem on Notion did not render; TokenInsight returned an
access error; The Defiant's article body did not load; blog.shib.io did not resolve. The LayerZero
report was read after text extraction from the PDF.
