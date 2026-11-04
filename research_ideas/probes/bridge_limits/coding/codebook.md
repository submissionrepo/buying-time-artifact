# Codebook for the bridge failures (blind recoding)

You code each failure in `blind_input.csv` from its mechanism description, its notes and the public
sources listed in the row, which you should open. Do not open `results/incidents.csv`,
`results/incident_coding.csv` or any file that carries earlier codings, and do not search the
repository for them: this coding must be independent of the earlier ones.

A bridge transfer passes four stages:
1. **send**: a contract on the sending chain records a deposit (a lock or a burn) and emits an event;
2. **verifiers**: the bridge's verifiers (a validator set, a multisig, an MPC committee, an oracle
   network, a relayer, or a light client) attest to the event;
3. **check**: a component on the receiving side checks the attestation and the message;
4. **release**: the receiving side releases value: it pays from an escrow or a liquidity pool, or it
   mints a wrapped asset.

## Fields

**class** (one value; where the unauthorized withdrawals entered):
- `EVENT`: the sending chain (its contract, node software or transfer code) recorded a deposit that
  moved no value, and the rest of the bridge honored it.
- `KEYS`: keys that authorize releases (validator, multisig, MPC, deployer, owner or admin keys) were
  under the control of a party outside the operating team, so the releases carried valid
  authorizations. A key obtained through a software flaw (nonce reuse, weak key generation, a flaw in
  a threshold-signature scheme) is KEYS.
- `CHECK`: a check that should have rejected the release accepted a message, proof or event that
  matched no valid deposit, with no authorizing key taken.
- `OTHER`: none of the above (an accounting flaw within one chain, a liquidity provider's or solver's
  own key, no published root cause).

**check_location** (CHECK only): `receiving_contract` (the flawed check is in the contract or program
on the receiving chain), `offchain_verifier` (the flawed check is in off-chain software of the
verifiers, relayer or sequencer that then signs or authorizes the release), or `unknown`.

**legs**: list every release leg as `chain:side:share`, separated by `;`, where side is one of
`escrow`, `mint`, `pool`, `other`, and share is the approximate share of the failure's value released
on that leg (shares may add to more than 1 when a minted claim is later redeemed from an escrow; then
give both legs and say so in the notes). Example: `Solana:mint:1.0;Ethereum:escrow:0.78`.

**legs_through_verifiers**: for each leg in the same order, `yes` if the releases on that leg were
attested or signed by the bridge's verifier set (so a limit inside the verifiers' signing software
would have metered them), `no` if they bypassed the verifiers, `unknown` otherwise. A redemption of
minted claims back through the bridge is usually `yes`: the verifiers attest the burn of the claims.

**release_point_contract**: `yes` if the value on the main leg left a smart contract or program that
could host a limit (the operator could add or wrap one without moving custody to new keys), `no` if
the value was held directly by keys (externally owned accounts, MPC or multisig wallets without
contract logic, a federation's Bitcoin wallet, an exchange-style hot wallet) or on a chain without
programmable custody, `unknown` otherwise.

**keys_controlled_release_contract** (KEYS only): `yes` if the taken keys also held the release
contract's owner, admin, upgrade or configuration role, or custody sat at the keys themselves; `no` if
the taken keys only signed messages while a separate role set parameters; `unknown`.

**pause_holder**: `independent_of_failure` (a party whose keys were not taken and whose code was not the
failing code could stop releases), `controlled_by_failing_party`, `no_pause_function` (no pause on the
path, including custody held directly at the taken keys), `unknown`.

**first_response_type**: the first public response that the row's sources document: `onchain_pause`
(a pause or halt transaction or a chain halt you can date), `operator_post` (a statement by the
operator), `third_party` (only third parties are documented), `unknown`.

**confidence**: `high`, `medium` or `low` for the class.

**rationale**: one or two sentences, with the source that settled the class.

## Output

Write `blind_coding.csv` in this directory with the columns
`id,class,check_location,legs,legs_through_verifiers,release_point_contract,keys_controlled_release_contract,pause_holder,first_response_type,confidence,rationale`
and one row per failure, and `blind_coding_notes.md` with the cases you found hard and why. Use
neutral, factual language. Do not write addresses or transaction hashes into either file.
