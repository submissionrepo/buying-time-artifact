# E24: releases from the Ethereum custody contract before the failure

File: `E24.csv` (535 rows; columns ts_utc, leg, asset, amount, usd, kind, priced).
Scripts: `collect_legit_E22_E24.py` (collect, events, price, write), `stats_E22_E24.py` (figures below).
Raw caches (addresses and transaction identifiers stay there): `raw/E24/`.

## Window

- 150 days ending one second before the first unauthorized release (2023-11-22T09:59:35Z):
  2023-06-25T09:59:35Z to 2023-11-22T09:59:34Z.
- Ethereum blocks 17,555,757 to 18,626,539 (the next block holds the first unauthorized release).

## Release point

One leg, `custody`: the bridge's custody contract on Ethereum (`E24_eth` in `onchain_targets.json`).
A withdrawal takes two operator confirmations. Each confirmation emits a `Withdrawing...` event; the
second one executes the transfer and emits a `WithdrawDone...` event (token and native variants).

## How releases were captured

- ERC-20: every `Transfer` log with the custody contract as sender (`eth_getLogs`, 5,000-block steps).
- Native ether: `trace_filter` with the custody contract as caller; calls with value above zero,
  call type `call`, no error, not inside a reverted transaction (kind `native`, 32 rows).
- Cross-check against the contract's own release events: the 503 ERC-20 releases match the 503
  `WithdrawDoneToken` events one to one (transaction, token, amount), and the 32 native releases
  match the 32 `WithdrawDoneNative` events (transaction, amount). The confirmation events number
  1,006 for tokens (2 per release) and 65 for native ether (2 per release plus one, see Exclusions).

## Exclusions

- Movements to the bridge's own addresses: none identified. All 535 releases in the window went to
  a single externally owned account. That account is not among the accounts calling the release
  function (the operators), and none of the 138 deposits pulled into the custody contract in the
  window came from it. The inputs do not identify it as the operator's own, so its releases stay in.
- Failure: no release in the window went to a recipient of the failure. One native confirmation in
  the last block of the window, to an account with no prior transactions, was not executed within
  the window; it is not a release and is treated as part of the failure.
- Token events not initiated by the custody contract: none.

## Pricing

DefiLlama `coins/batchHistorical` at each release time: first with a 10-minute search width, then a
2-hour width for misses (6 rows priced with a gap above 10 minutes, at most 99 minutes). HBTC has no
DefiLlama price and is valued at the BTC price (the `price_alias` in `onchain_targets.json`, a peg
assumption). Other wrapped tokens of the operator (HFIL, HDOT, HBCH) are priced from their own
DefiLlama series where one exists. Rows without a price stay unpriced.

## Totals

- Releases: 535 (503 ERC-20, 32 native), on 75 of the 150 days.
- Priced: 528 of 535 (98.7%); priced USD 57,257,945 (ERC-20 51,148,569; native 6,109,376).
- Unpriced (7 rows, token amounts): LAMB 1 (3,068,384 units), NEST 2 (610,956), BIX 1 (428,271),
  MATIC 1 (7,059), HBSV 1 (38), HBCH 1 (23).
- By asset (priced USD): MX 26.1M (121 releases), USDT 17.4M (34), ETH 6.1M (32), HBTC 5.6M (14),
  WOO 0.8M (31), HFIL 0.6M (135); the other 20 assets together under 0.7M.
- Single release (priced): median 6,591 USD; 99th percentile 993,235 USD.
- Daily priced USD over the 147 days from the first to the last release: median 892; mean 389,510;
  90th percentile 1,458,842; 72 of those days have no release.

## Peaks

- Largest single release: 1,635,926 USD (45 HBTC, 2023-11-17 01:32:59 UTC). The largest stablecoin
  releases are three USDT releases of 1,547,399 each within 27 minutes on 2023-10-17.
- Busiest hour: 2023-10-17 08:00 UTC, 5,859,477 USD in 20 releases (also the busiest hour by count).
- Busiest day by USD: 2023-10-17, 8,919,210 USD in 39 releases, the first day of releases after a
  33.5-day pause. Busiest day by count: 2023-07-10, 41 releases.

## Gaps and caveats

- Releases are sparse and bursty: pauses of 15.7 days (ending 2023-09-08), 33.5 days (ending
  2023-10-17) and 10.7 days (ending 2023-11-09); the last release is 4.2 days before the failure.
- Every release went to one account, so the series records that single counterparty's withdrawals
  (possibly an account of the affiliated exchange; not verified), not dispersed user traffic.
- HBTC (5.6M USD) is valued under a peg assumption; 1.3% of releases are unpriced.
- Releases cluster on days with large withdrawals, so a fit on daily totals rests on few active days.
