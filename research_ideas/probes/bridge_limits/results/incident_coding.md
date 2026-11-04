# Coding of the 57 bridge-set failures

- Date: 2026-10-16. Row-level file: `results/incident_coding.csv` (one row per failure with `in_bridge_set = yes`; sources as URLs). Built from `results/incidents.csv`, `incidents/curation.py` and `data/incidents/research/batch_*.json`; two public pages were read to settle fields (Rekt's Poly Network page for the BSC asset list of E05; Verichains' Hyperbridge analysis for the mechanism of E44). Chain caches in `data/incidents/onchain/` were used only to count released tokens. No addresses or transaction hashes appear here or in the CSV.
- Procedure note: the class was coded from the failure descriptions, the research-note quotes and the post-mortems. The first data listing printed the existing `failure_class` column next to the names before coding began, so the recoding was not blind to it; the comparison below should be read with that in mind.

## Coding rules

- **class_recoded.** S: the sending chain (its contract, node software or transfer code) recorded a lock, deposit or burn that moved no value, and the release side honored it. V: keys that authorize releases (validator, multisig, MPC, deployer, owner or admin keys) were under outside control, so releases carried valid authorizations. D: the check in the receiving contract, or in the off-chain verifier that authorizes the release, accepted a message, proof or event that matched no valid lock or burn, with no authorizing key taken. O: other (single-chain accounting flaws, a liquidity provider's own key, no published root cause). Where a key was obtained through a software flaw (nonce reuse, weak key generation, threshold-signature flaw), the class is V and the borderline tag `combined_key_and_flaw` is set. A party's own inventory key (a solver) is O, not V.
- **detection_channel.** `detection_basis = stated` when a source names how the operator learned (own monitoring, a validator channel, a white-hat report, a failed user withdrawal, a firewall shortfall). `inferred_order` when no source names the channel but a public outside alert preceded the operator's first public action or statement; the channel is then coded `third_party_alert`. Operator statements of the form 'we detected' or 'we identified' count as `operator_monitoring` only when no outside alert preceded the operator's first action. Everything else is `unknown`.
- **pause_holder.** `independent_of_failure`: a party whose keys were not taken and whose code was not the failing code could stop releases (contract pause, validator or node halt, prover or relayer stop). `controlled_by_failing_party`: the pause or the release contract's control sat with the taken key. `no_pause_function`: no pause existed on the path used, including custody held directly at a taken key (MPC addresses, hot wallets, vault keys), where stopping the operator's service does not bind the key holder, and immutable contracts. `unknown`: a pause existed but its holder relative to the taken keys is not reported.
- **keys_controlled_release_contract (V only).** yes when the taken key held the release contract's owner, admin, upgrade or configuration role, or when custody sat at the key itself (no contract in between); no when a source or the verified contract roles show the taken key only signed messages while a separate role set parameters; unknown otherwise. Several `no` codings rest on the contract roles described in the sources rather than an explicit statement; the note says so.
- **same_flaw_reaches_release_limit (D only).** yes when the flaw or the path it opened could change or sidestep a limit stored in the releasing contract (a quota keyed to the forged signer; a forged governance message that hands over the token's admin role). no when the false message, proof or event passes through the ordinary release function, where a cap would be evaluated. unknown when the flaw also reconfigured the bridge (a trusted-source list) or granted a privileged role whose limit treatment depends on the design.
- **n_chains_released / n_assets_released.** Chains from which unauthorized value left an escrow or on which unbacked claims were issued (onward moves of released value are not counted). Assets are counted as (chain, token) positions drained or issued, so a token minted on one chain and redeemed from an escrow on another counts twice. `>=` marks a lower bound; empty means not determined in the sources read.
- **recovered_usd** = returned_usd (sent back by the recipient, or seized and transferred) + frozen_usd (frozen in place by an issuer, validator upgrade, exchange or governance), as reported; 0 when none is reported. Operator reimbursement from its own funds is excluded. Overlaps that sources leave open (E13) are noted.
- **minted_value_basis** (failures with release side mint, both, or undetermined): `nominal_at_mint` (minted quantity times the backed asset's market price at the release, including minted claims redeemed against an escrow), `realized_on_sale` (proceeds of selling or borrowing against the minted claims), `as_reported` (a figure taken from the operator or press whose valuation basis is not the two above). `n.a.` for escrow-only failures.
- **borderline.** Tags from a fixed list, several per failure where they apply. One tag was added because none of the listed ones fits: `verifier_inputs_falsified` (the verifier's keys were intact but the data it attested were controlled).

## Counts per field (57 failures)

- class_recoded: S 5; V 20; D 27; O 5. Existing failure_class: D 26; S 6; V 20; O 5. Agreement 53 of 57.
- Value share by class_recoded: S 11.1%; V 31.2%; D 57.2%; O 0.5% (existing: S 11.1%; V 29.3%; D 59.3%; O 0.3%), of 3,710.8M USD.
- detection_channel: operator_monitoring 10; third_party_alert 21; user_report_or_failed_withdrawal 1; escrow_or_balance_shortfall 1; other 1; unknown 23. detection_basis: inferred_order 17; none 23; stated 17.
- pause_holder: independent_of_failure 39; controlled_by_failing_party 4; no_pause_function 9; unknown 5.
- keys_controlled_release_contract (V, n = 20): yes 12; no 5; unknown 3.
- same_flaw_reaches_release_limit (D, n = 27): no 23; unknown 2; yes 2 (yes: E44, E02; unknown: E32, E27).
- n_chains_released: 1 chain 36; 2 chains 11; 3 to 5 6; 10 or more 3; not determined 1.
- n_assets_released: 1 asset 17; 2 to 5 14; 6 to 20 12; over 20 2; lower bounds only 8; not determined 4.
- recovered_usd > 0: 20 failures, 1,743.7M USD (47.0% of bridge-set value); returned 1,125.3M, frozen 618.4M. Without E05 (all returned) and E16 (frozen by chain halt): 697.2M.
- minted_value_basis (n = 18 with mint, both or undetermined release side, plus E42 coded from its mint leg): as_reported 8; nominal_at_mint 6; realized_on_sale 4.
- borderline tags: light_client_or_proof 20; none 20; admin_or_upgrade_key 10; combined_key_and_flaw 5; verifier_set_rewritten 4; verifier_inputs_falsified 2; arbitrary_call_in_release_contract 1.

## Failures where class_recoded differs from failure_class

| id | name | failure_class | class_recoded | reason for the recoded class |
|---|---|---|---|---|
| E46 | TAC TON-TAC bridge (unbacked mint on TAC, release on TON) | S | D | the sequencer that authorizes mints did not check the code of the jetton wallet sending the deposit notice (post-mortem) |
| E40 | Garden (inventory of one independent solver) | V | O | the leaked key belonged to an independent solver's own inventory wallets, not to a bridge verifier or release contract |
| E27 | SaitaChain XBridge (Ethereum custody contract) | O | D | the custody contract's own authorization check failed: any caller could overwrite a token's lister record and then use the lister-only withdrawal |
| E25 | Orbit Bridge (Ethereum vault) | D | V | seven of ten registered validators signed six withdrawals at amounts matching no deposit; correct signatures from a quorum point to control of the signing hosts, although the operator denies key theft |

## Borderline cases

| id | class_recoded | tags | note |
|---|---|---|---|
| E05 | D | verifier_set_rewritten;arbitrary_call_in_release_contract | the forged message rewrote the keeper set through an arbitrary call from the release-side manager; later releases carried signatures of the new set |
| E06 | D | light_client_or_proof | the off-chain node both verifies origin events and signs the release, so the event check is the receiving check; the events came from outside contracts (S reading possible) |
| E11 | D | light_client_or_proof | signature verification sits in the receiving program, so the verification and the receiving check are the same code |
| E34 | V | admin_or_upgrade_key | the releases used the contract's admin role rather than a verifier quorum |
| E35 | D | light_client_or_proof | the proof verifier is the receiving check |
| E37 | V | combined_key_and_flaw | key control was combined with flash-borrowed stake to pass the checkpoint |
| E38 | V | admin_or_upgrade_key | configuration change with a privileged key rather than a verifier signature |
| E39 | V | admin_or_upgrade_key | D reading possible: the receiving contract accepted messages from a peer it had been configured to trust |
| E45 | D | verifier_inputs_falsified | verifier keys intact but its inputs were controlled; V reading if verifier infrastructure counts as verifier control |
| E46 | D | light_client_or_proof | the sequencer is both verifier and minter; S reading possible because the deposit notice came from a counterfeit wallet on the sending chain |
| E47 | V | combined_key_and_flaw | the key was obtained through a flaw in the threshold-signature implementation |
| E48 | D | light_client_or_proof | the contract verifies notarized export data itself, so verification and the receiving check are the same code |
| E58 | D | light_client_or_proof | the signature check sits in the treasury validator script, so verification and the receiving check are the same code |
| E64 | S | light_client_or_proof | the same functionaries validate the sidechain and sign peg-outs, so the origin-chain check and the release check share node software (D reading possible) |
| E49 | S | none | V reading (first alerts, DefiLlama) and D reading (the Ethereum contract accepted any denomination string) are possible; no post-mortem |
| E50 | D | light_client_or_proof | the SPV relay in the receiving contract is the verification; S reading possible because the origin chain accepted duplicate commitments |
| E51 | D | none | S reading for the escrow leg: the minting chain recorded burns of unbacked tokens |
| E52 | D | light_client_or_proof | the rollup proof check in the L1 contract is the receiving check |
| E53 | D | light_client_or_proof | the proof verifier is the receiving check |
| E55 | V | combined_key_and_flaw;verifier_set_rewritten | the leaked key worked only because the attestation check accepted a debug-mode enclave; the attacker added its own verifier instance (D reading possible) |
| E56 | D | light_client_or_proof | the relayer's event reader is both verifier and releaser; S reading possible since the events came from outside the deposit program |
| E31 | D | none | eight addresses frozen on Neo N3, amount not stated |
| E32 | D | verifier_set_rewritten | the first forged message added its source to the trusted-source whitelist |
| E40 | O | admin_or_upgrade_key | V reading if the solver's key counts as a release authority |
| E42 | V | admin_or_upgrade_key | an owner key used to upgrade the verifying contract rather than a verifier quorum |
| E44 | D | light_client_or_proof;admin_or_upgrade_key | the proof flaw admitted a governance message that handed over the token's admin role |
| E60 | D | light_client_or_proof | the contract verifies the export proof itself; S reading possible since the Verus chain notarized a hand-crafted export |
| E62 | D | light_client_or_proof | the receipt check in the destination shard is the receiving check |
| E67 | D | light_client_or_proof | the proof verifier is the receiving check |
| E69 | O | none | S or D readings possible once a root cause is published |
| E17 | V | admin_or_upgrade_key;combined_key_and_flaw | the deployer key was recoverable because of a flaw in the key-generation tool |
| E18 | V | admin_or_upgrade_key | the release used the owner-only function rather than a verifier quorum |
| E27 | D | none | no cross-chain message is involved; O reading possible |
| E28 | V | admin_or_upgrade_key | an upgrade key replaced the release code |
| E13 | V | none | overlap between the 30M seizure, the 5.7M return and the 40M freeze is not stated |
| E15 | D | light_client_or_proof | the message-proof check sits in the receiving contracts |
| E16 | D | light_client_or_proof | the proof verifier is the receiving check |
| E25 | V | verifier_inputs_falsified | no root cause published; the operator denies key theft and a contract flaw, so the signers may have been fed false data |
| E30 | D | verifier_set_rewritten;admin_or_upgrade_key | a governance upgrade set the required verifier weight to zero |
| E01 | V | combined_key_and_flaw | the key was obtained through a nonce-reuse flaw in signing |
| E02 | D | light_client_or_proof | signature verification is the receiving check |
| E03 | D | light_client_or_proof | the observer both verifies deposits and authorizes outbounds |
| E04 | D | light_client_or_proof | the observer both verifies deposits and authorizes outbounds |
| E12 | S | none | release side not determined |

## Fields left open

- Detection channel unknown for E05, E23, E34, E35, E38, E39, E46, E50, E56, E57, E31, E32, E41, E44, E63, E67, E18, E21, E27, E16, E01, E02, E12: no source names how the operator learned and no outside alert preceded it.
- Asset or chain counts not determined: E56, E42, E28, E12.
- `inferred_order` codings say only that a public outside alert came first; they do not show that the operator read it.
