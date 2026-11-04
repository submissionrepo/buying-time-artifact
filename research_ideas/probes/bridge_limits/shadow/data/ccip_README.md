# CCIP releases between Ethereum and BSC, 2026-09-04 to 2026-10-16 (UTC)

`ccip_ethereum-bsc_releases.csv`: one row per token that a Chainlink CCIP message from the other chain released or
minted on the destination chain, for every message executed successfully in [2026-09-04T00:00Z,
2026-10-16T00:00Z), both directions. Built by `shadow/ccip_collect.py` (steps pair, targets, releases, sources,
build, coverage, selftest) with the decoding of `shadow/ccip_decode.py`, which the live monitor
(`shadow/live_monitor.py`) shares. The file carries no addresses and no transaction hashes; `shadow/raw/ccip/`
(not in the artifact) keeps them.

| direction | releases | USD | unpriced | matched | value moved | agrees |
|---|---|---|---|---|---|---|
| ethereum->bsc | 2,350 | 12.9M | 14 | 2,350 | 2,350 | 2,350 |
| bsc->ethereum | 1,020 | 7.1M | 3 | 1,020 | 1,020 | 1,020 |

## Pair

The explorer API (`api.ccip.chain.link/v2/messages`, crawled back to 2026-07-01 with source and destination
filters) counted, for the period, 3,367 successful token-carrying messages between Ethereum and BSC (2,348 and
1,019 by direction) and 3,229 between Ethereum and Base. The pair with more messages in both directions was taken;
it is also the pair of the Wormhole table.

## Columns

- `pair`: source->destination chain. `release_ts_utc`, `release_block`: the execution's block on the destination.
- `token`, `amount`: the released token's symbol and the amount in its units (destination decimals).
- `usd`: amount times DefiLlama's price of the destination token at the release (hourly series within 2 hours,
  else daily within 36 hours); empty when neither exists.
- `kind`: `pool_mint` (the destination pool minted the token) or `pool_release` (paid out of the pool's custody).
- `matched`: yes when the source chain holds the OnRamp's send event with the release's message id (on Ethereum
  from a scan of the OnRamps over the period and the 7 days before, indexed by message id; on BSC from the
  explorer's send transaction, accepted only if its receipt holds the send event with the same message id; for the
  rest by the OnRamp's sequence counter, `ccip_decode.find_source`).
- `src_ts_utc`, `src_block`, `deposit_age_s`: the send's block, and the release time minus the send time.
- `value_moved`, `value_detail`: yes when the send transaction moved the amount into the source token pool
  (`pool_lock`: kept there or handed to a custody contract; `pool_burn`: burned), counting only logs between the
  previous send event of the transaction and this one.
- `amount_agrees`: yes when the message's token, amount (converted from the source token's decimals as the
  destination pool does) and recipient equal the release's.
- `note`: the ramp version (1.5, 1.6 or 2.0) and anything unusual (a send before the period, a locked amount moved
  on from the pool, a source located by the sequence search).

## Coverage and checks

- Against the explorer: every explorer message of the period (2,348 and 1,019) is in the table; the table has 3 more
  (2 and 1), sent before the crawl's cutoff, each confirmed by the explorer's per-message endpoint as executed
  successfully with tokens. Daily counts agree on 41 of 42 days in each direction, the other day by these
  messages. The explorer's 492 and 1 token messages with status FAILED reverted on execution and released nothing.
- Self-test: `find_source` on 40 random releases per direction found the same send event as the bulk index, and
  `new_releases` through a plain client without caching found the same releases on a short block range.
