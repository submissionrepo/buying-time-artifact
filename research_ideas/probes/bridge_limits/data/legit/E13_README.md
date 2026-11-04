# E13: releases from the Ethereum gateway before the failure (March 2022)

File: `E13.csv` (64,028 rows; columns ts_utc, leg, asset, amount, usd, kind, priced).
Script: `build_legit.py E13` (collect, reconcile, price, write; figures below come from its
`raw/E13/summary.json` and from `E13.csv`).
Raw caches (addresses and transaction identifiers stay there): `raw/E13/`.

## Window

- 150 days ending one second before the first unauthorized release (2022-03-23T13:29:09Z):
  2021-10-24T13:29:09Z to 2022-03-23T13:29:08Z.
- Ethereum blocks 13,480,462 to 14,442,834 (block times 2021-10-24T13:29:25Z to 2022-03-23T13:28:37Z;
  the next block holds the first unauthorized release).

## Release point

One contract: the bridge's v1 Ethereum gateway (custody leg `E13_eth` in `onchain_targets.json`). It
holds the escrowed assets and releases them against validator signatures. No other custody contract of
this bridge is involved on Ethereum.

## How releases were captured

- Release record: the gateway's `TokenWithdrew(id, owner, token, amount)` event, one per completed
  release (64,070 in the window). One event is one row, kind `event`.
- Reconciliation by transaction:
  - ERC-20: all `Transfer` logs with the gateway as sender (18,618) matched a release event of the same
    token in the same transaction.
  - Native ether: `trace_filter` with the gateway as caller, value-bearing `call` frames (202,094).
    The gateway holds WETH and pays ether releases in native ether: each of the 45,452 WETH-denominated
    release events has a native call in its transaction. Of the rest, 153,053 calls wrap incoming
    deposits into WETH (internal), 8 go to the gateway itself (internal), and 3,581 lie in transactions
    that reverted (receipt status 0, each checked), so nothing moved.
  - Hence no `erc20` or `native` rows: every outflow of the gateway in the window is a release event.
- The v1 gateway emitted no lock or limit events; it had no withdrawal limit (see `incidents.csv`).
- Timestamps: block time of the event.
- Deposits (171,934 `TokenDeposited` events) are inflows and are not used.

## Exclusions

- 42 release events whose recipient is the gateway itself (internal movement), plus the internal native
  calls above.
- Releases belonging to the failure: none in the window; both unauthorized releases fall in blocks from
  14,442,835 on. No release in the window went to the failure's recipient.
- Kept, but flagged: two very large ether releases to externally owned accounts, 116,737 ETH
  (356.1M USD, 2022-02-11T02:45:17Z) and 124,519.29 ETH (366.3M USD, 2022-02-14T13:27:58Z). They were
  ordinary signed releases; the chain data alone does not show whether the recipients belong to the
  operator, so they are not excluded. One recipient held over 230,000 ETH before the release and has a
  transaction count in the thousands; the other forwarded nearly all of the amount within the window.
  Figures without them are given below.
- Label check (2026-10-16): Etherscan's public name tags (from a Dune label compilation) attribute both
  recipients to wallets of one exchange (Binance), and 40 minutes after the first release a wallet with
  the same exchange's tag deposited the same 116,737 ETH back into the gateway. Both are withdrawals by a
  large holder, not movements of the operator, so they stay in the series; the variant without them
  remains a sensitivity check. Addresses stay in the raw cache.

## Totals

| asset | releases | amount | USD at the time |
|---|---:|---:|---:|
| ETH (released from WETH as native ether) | 45,419 | 811,882.62 | 2,693,320,469 |
| AXS | 4,952 | 7,505,213 | 651,468,323 |
| SLP | 10,800 | 4,992,371,289 | 244,777,279 |
| USDC | 2,857 | 51,636,567 | 51,682,140 |
| **all** | **64,028** | | **3,641,248,210** |

- Priced: 64,028 of 64,028 rows (100%). All prices from the DefiLlama `/chart` hourly series, nearest
  point within 2 h. The default request leaves holes of up to 29 days in late 2021; those 500-hour blocks
  were refetched with a 1,800 s search width, which fills them.
- Release size: median 916 USD, 90th percentile 26,302, 99th 724,973, 99.9th 6.29M.
- Daily totals (all 150 UTC days): mean 24.1M, median 12.1M, 90th percentile 51.5M, 99th 260.8M,
  maximum 385.7M.
- Largest single release: 124,519.29 ETH (366.3M USD) at 2022-02-14T13:27:58Z.
- Busiest hour: 2022-02-14 13:00 UTC, 375.0M USD in 15 releases.
- Busiest day: 2022-02-11, 385.7M USD.

Without the two flagged releases (64,026 rows): total 2,918.8M USD; largest release 11,690 ETH
(47.0M USD, 2021-12-16T07:03:59Z); busiest hour 2022-02-06 08:00 UTC, 56.8M USD in 16 releases;
busiest day 2022-01-29, 140.6M USD; daily mean 19.3M, median 12.1M, 90th percentile 39.9M, 99th
112.4M.

## Gaps

- No interval longer than 6 hours without a release.
- No unpriced rows.
- Recipient roles are not labelled: apart from the gateway itself, movements to other operator
  addresses could not be identified and stay in the series. The two flagged releases are the only ones
  above 20,000 ETH.

## Fit for a limit

Complete for the gateway: every outflow in 150 days is accounted for by a release event and all of it
is priced. A limit fitted to this series should be reported with and without the two flagged
releases, since together they are 20% of the window's USD and set the daily and hourly maxima.
