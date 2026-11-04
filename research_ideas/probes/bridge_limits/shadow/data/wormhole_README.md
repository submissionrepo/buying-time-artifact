# Wormhole token bridge releases, ethereum and bsc, 2026-09-04 to 2026-10-16

Shadow-run input for the deposit-backing check. Built by `shadow/wormhole_collect.py` on 2026-10-16 from public RPC endpoints; `shadow/wormhole_decode.py` holds the decoding, shared with the live monitor.
Data: `wormhole_ethereum_bsc_releases.csv`, one row per release in [2026-09-04T00:00:00Z, 2026-10-16T00:00:00Z), sorted by time. The CSV and this README carry no addresses and no transaction hashes; the raw caches that do (RPC answers, API pages, contract addresses) stay in `shadow/raw/wormhole/` and are not committed.

## Pair

TransferRedeemed events of the token bridge on each of the seven candidate chains over 2026-10-09 to 2026-10-16 (the period's last week), counted by emitter chain. A pair's score is the releases in both directions combined:

| pair | first -> second | second -> first | both |
|---|---:|---:|---:|
| ethereum and bsc | 734 | 1,064 | 1,798 |
| bsc and base | 250 | 243 | 493 |
| ethereum and base | 250 | 227 | 477 |
| bsc and polygon | 85 | 124 | 209 |
| ethereum and avalanche | 46 | 36 | 82 |
| ethereum and arbitrum | 31 | 38 | 69 |

Ethereum and BSC lead by a factor of 3.6 over the next pair. Redeem events on each chain in that week, all emitter chains: bsc 2,888, ethereum 2,631, base 879, polygon 210, arbitrum 209, avalanche 84, optimism 58. Most of the rest come from non-EVM chains (Solana, Near, Sui), which fall outside the EVM pair.

## Contracts and their roles

- Core contract (one per chain). Every message goes through it; it emits `LogMessagePublished(sender, sequence, nonce, payload, consistencyLevel)`, and its sequence counts up by one per sender.
- Token bridge (one per chain), the sender of transfer messages. On the source chain it takes a token native to that chain into custody, wrapping the gas coin first, or burns a wrapped token it issued, and publishes a transfer message. On the destination chain it completes the transfer from the guardian-signed message: it emits `TransferRedeemed(emitterChainId, emitterAddress, sequence)` and then releases the tokens.
- Wrapped gas coin (WETH on Ethereum, WBNB on BSC), the custody form of the gas coin; the token bridge names it (`WETH()`).

Addresses: `CONTRACTS.MAINNET` in `sdk/js/src/utils/consts.ts` and `knownTokenbridgeEmitters` in `sdk/mainnet_consts.go` of the wormhole-foundation/wormhole GitHub repository (main, commit bb5957f321b0, 2026-10-13), and the mainnet tables of the documentation's contract-addresses page (core contracts; Wrapped Token Transfers, the documentation's name for the token bridge), accessed 2026-10-16. For all seven chains the three lists agree (core and token bridge in the SDK and the documentation; the token bridge's emitter in the Go list is the token bridge's address).

On chain, for each of the seven chains: the endpoint's chain id is the expected EVM chain; both contracts have code; the core contract's and the token bridge's `chainId()` return the Wormhole chain id; the token bridge's `wormhole()` is the core contract; the token bridge's `bridgeContracts(c)` returns the other six token bridges' emitters; the token bridge names a wrapped gas coin. In the pair week the core contract emitted LogMessagePublished from the token bridge (ethereum 2,151, bsc 3,258, polygon 281, avalanche 92, arbitrum 177, optimism 34, base 748) and the token bridge emitted TransferRedeemed on every chain. Every redeem event's emitter equals the registered token bridge of its chain.

## Method

Period: [2026-09-04T00:00:00Z, 2026-10-16T00:00:00Z) by release block time; the block ranges are the first block at or after each midnight UTC (bsc blocks 119,818,926 to 127,878,729, last block before the period at 2026-09-03T23:59:59Z, first after at 2026-10-16T00:00:00Z; ethereum blocks 25,900,227 to 26,201,364, last block before the period at 2026-09-03T23:59:59Z, first after at 2026-10-16T00:00:11Z).

1. Releases. Every TransferRedeemed of the destination token bridge whose emitter chain and emitter are the source chain's token bridge (topics filter), then the receipt of its transaction. The token movement is taken from the logs after the event and before the next TransferRedeemed in the same transaction (the token bridge emits the event, then pays a relayer fee if the message names one, then pays the recipient): a Transfer out of the token bridge (`unlock`), a mint of a token for which the token bridge's `isWrappedAsset` is true (`mint`), or a Withdrawal of the wrapped gas coin by the token bridge (`unlock_native`; the gas coin itself is paid by an internal call, read from a `debug_traceTransaction` call trace). A burn by the token bridge in the same stretch belongs to an outgoing transfer and is skipped. `amount` is the whole release in token units (recipient plus relayer fee), `token` the symbol of the released token (the gas coin's symbol for `unlock_native`). Transfers with payload (payload 3), redeemed by the contract named in the message, are included like plain transfers.
2. Source messages. LogMessagePublished of the source core contract with the source token bridge as sender, scanned in bulk from three days before the period to its end and indexed by sequence. A release whose sequence is older than the scan is located with the timestamp of the signed message found in the release transaction's input (the guardians copy the source block's time into it): a log query around that time on the source chain. The transfer payload is decoded: payload id, normalized amount (8 decimals), token address and chain, recipient, target chain, relayer fee (payload 1) or sender (payload 3).
3. Value moved. In the source transaction, between the token bridge's previous message and this one: for a token native to the source chain, a Transfer of that token into the token bridge, or a Deposit of the wrapped gas coin credited to it (`lock`); for a wrapped token, a Transfer of the wrapped token from the token bridge to the zero address (`burn`), the wrapped token being the source token bridge's `wrappedAsset(tokenChain, tokenAddress)`. `value_moved` is yes when such a movement exists and its amount, normalized to 8 decimals, equals the message's amount.
4. Agreement. `amount_agrees` is yes when the message's amount, de-normalized to the released token's decimals, equals the release (recipient plus fee), the message's token (chain and address) equals the released token's origin (for a wrapped token its `chainId()` and `nativeContract()`, read on the destination), and the message's recipient equals the release's recipient. The target chain and, for two-part releases, the fee are checked as well and listed in the notes when they differ.
5. Prices. DefiLlama coins API, as `data/legit/build_e59.py` does: the hourly chart point nearest the release within 2 hours, else the daily point within 36 hours. The coin is the released token for an unlock and the origin token on its own chain for a mint, each falling back to the other.
6. `deposit_age_s` is the release block time minus the source block time.

## Counts

| | ethereum->bsc | bsc->ethereum |
|---|---:|---:|
| releases | 4,278 | 5,613 |
| USD value (priced releases) | 4.22M | 5.26M |
| unpriced releases | 233 | 354 |
| kind unlock / mint / unlock_native | 625 / 3,650 / 3 | 4,072 / 1,541 / 0 |
| payload 1 / payload 3 | 4,110 / 168 | 5,263 / 350 |
| relayer fee in the message | 0 | 0 |
| matched to a source message | 4,278 | 5,613 |
| value moved: lock / burn | 2,874 / 1,404 | 809 / 4,804 |
| value moved = yes | 4,278 | 5,613 |
| amount, token and recipient agree | 4,274 | 5,604 |
| message published before the period | 13 | 26 |
| located singly (older than the bulk scan) | 13 | 26 |
| deposit age min | 12.9 min | 3 s |
| deposit age p1 | 13.0 min | 6 s |
| deposit age median | 16.4 min | 19 s |
| deposit age p99 | 54.4 min | 2.4 h |
| deposit age max | 152.7 d | 148.6 d |

Largest tokens by value, ethereum->bsc: GWEI 1.6M, XAN 0.6M, GRVT 0.5M, NPC 0.3M, LUNA 0.3M, RSR 0.3M.
Largest tokens by value, bsc->ethereum: GWEI 3.2M, XAN 0.5M, NPC 0.3M, LUNA 0.2M, B 0.2M, GRVT 0.1M.

## Releases that did not match or whose value did not move

- ethereum->bsc, 2026-09-11T22:34:06Z: 808268952.2290146144 SHIBKILLER (unlock); matched yes, value moved yes, agrees no; no price; disagrees: amount, fee
- ethereum->bsc, 2026-09-11T22:34:13Z: 326621652.437376791 MOONWENPEPE (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- ethereum->bsc, 2026-09-11T22:34:13Z: 494433726.8682048094 MOONWENPEPE (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- ethereum->bsc, 2026-09-11T22:34:23Z: 877437664.9376605728 SHIBKILLER (unlock); matched yes, value moved yes, agrees no; no price; disagrees: amount, fee
- bsc->ethereum, 2026-09-13T16:53:59Z: 223525346.381437281 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- bsc->ethereum, 2026-09-13T20:50:23Z: 229781065.068946603 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- bsc->ethereum, 2026-09-14T02:28:35Z: 193462238.243160837 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- bsc->ethereum, 2026-09-15T01:17:35Z: 148537005.262938656 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- bsc->ethereum, 2026-09-16T10:18:47Z: 120462959.502865861 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- bsc->ethereum, 2026-09-18T21:32:23Z: 133625061.789587132 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- bsc->ethereum, 2026-09-19T22:32:47Z: 115553627.466840068 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- bsc->ethereum, 2026-09-20T05:02:11Z: 103984095.723471289 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee
- bsc->ethereum, 2026-09-20T14:40:47Z: 104335596.833683907 WONKA (unlock); matched yes, value moved yes, agrees no; 3 token movements after the redeem event; the first 2 of one token used; no price; disagrees: amount, recipient, fee

## Checks

- Source scan, ethereum->bsc: 14,825 messages of the source token bridge in blocks 25,878,705 to 26,201,364 (2026-09-01T00:00:11Z to 2026-10-15T23:59:59Z), sequences 681,697 to 696,521 with 0 missing; the core contract's `nextSequence(token bridge)` is 681697 just before the range and 696522 at its end, so the scan holds every message of the range: yes.
- Source scan, bsc->ethereum: 17,110 messages of the source token bridge in blocks 119,243,646 to 127,878,729 (2026-09-01T00:00:00Z to 2026-10-15T23:59:59Z), sequences 865,418 to 882,527 with 0 missing; the core contract's `nextSequence(token bridge)` is 865418 just before the range and 882528 at its end, so the scan holds every message of the range: yes.
- Signed message in the release transaction's input, ethereum->bsc: found for 4,278 of 4,278 releases; its payload equals the source message's payload 4,271 times (differs 0, payload not read 7); its timestamp equals the source block time 4,278 times (differs 0).
- Signed message in the release transaction's input, bsc->ethereum: found for 5,613 of 5,613 releases; its payload equals the source message's payload 5,598 times (differs 0, payload not read 15); its timestamp equals the source block time 5,613 times (differs 0).
- Agreement components, ethereum->bsc: amount=False 4, amount=True 4,274, fee=False 6, recipient=False 2, recipient=True 4,276, to_chain=True 4,278, token=True 4,278.
- Agreement components, bsc->ethereum: amount=False 9, amount=True 5,604, fee=False 9, recipient=False 9, recipient=True 5,604, to_chain=True 5,613, token=True 5,613.

## Columns

`pair` (source->destination), `release_ts_utc` and `release_block` (destination block), `token` (symbol of the released token), `amount` (token units), `usd` (at the release hour; empty when unpriced), `kind` (unlock, mint, unlock_native), `matched` (a source message with the release's sequence from the source token bridge exists), `src_ts_utc` and `src_block` (the message's block), `deposit_age_s`, `value_moved` (yes, no, or na when unmatched), `value_detail` (lock, burn, none), `amount_agrees`, `note` (payload 3, relayer fee, message older than the period, disagreements, no price).

## Interface for the live monitor (`shadow/wormhole_decode.py`)

- `new_releases(rpc_dst, dst_chain, from_block, to_block)`: list of release dicts for the configured pair (the other chain of the pair is the source), sorted by block and log index. Keys: `dst_chain`, `src_chain`, `emitter_chain`, `emitter`, `sequence`, `block`, `ts`, `tx`, `log_index`, `kind`, `token`, `symbol`, `decimals`, `amount_raw` (base units, recipient plus fee), `fee_raw`, `recipient`, `fee_to`, `moves`, `origin_chain`, `origin_address`, `vaa` (timestamp, nonce, consistency and payload of the signed message read from the transaction input, or None), `notes`.
- `find_source(rpc_src, src_chain, release)`: None when the source chain has no message from its token bridge with the release's sequence; otherwise a dict with `block`, `ts`, `tx`, `sequence`, `payload` (decoded transfer), `value_moved`, `value_detail`, `moved_raw`, `amount_agrees`, `agree` (amount, token, recipient, to_chain, fee), `vaa_payload_equal`, `vaa_ts_equal`, `note`.
- `rpc_*` is an `incidents/rpc.py` `Rpc`, or `wormhole_decode.Client(chain, cache_dir=None)`, which adds the endpoints tested on 2026-10-16, JSON-RPC batches, per-endpoint log ranges and a call trace for gas-coin payouts. `message_index(rpc_src, src_chain, b0, b1)` builds the sequence index the collector passes to `find_source` as `index=`.

## Reproduce

`python -I shadow/wormhole_collect.py targets | pairs | collect | traces | sources | crosscheck | coverage | build` (in that order; every step caches under `shadow/raw/wormhole/`).
