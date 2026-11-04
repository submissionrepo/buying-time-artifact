# E05 legitimate release history (lock proxy custody, Ethereum and BSC legs, 150 days before the failure)

File: `E05.csv` (one row per release; columns ts_utc, leg, asset, amount, usd, kind, priced).
Script: `collect_legit_E05_E25.py E05`. Raw RPC, metadata and price caches are under `raw/E05/`, and the numbers
below come from `raw/E05/summary.json` and `E05.csv`.

## Window and contracts

- Failure time: 2021-08-10 09:51:02 UTC, the first unauthorized release on any leg (`results/incidents.csv`).
- Window: 2021-03-13 09:51:02 UTC to 2021-08-10 09:51:01 UTC (150 days ending one second before the failure).
- Ethereum leg: the bridge's lock proxy, the custody contract for E05 in
  `data/incidents/onchain_targets.json`. Blocks 12,029,494 to 12,996,670.
- BSC leg: the bridge's BSC lock proxy. It was identified as the only contract that emitted the release event
  in the documented BSC failure blocks (5 events, one emitter). Blocks 5,641,252 to 9,905,818.
- Polygon leg: not collected. The only public endpoint that served historical logs for Polygon caps queries
  at 50 blocks, which would take about 118,000 calls for 150 days. The other endpoints tried (2026-10-16) were
  over plan limits, required a key, reset the connection or did not resolve. Polygon carried about 14% of the
  failure's value.

## How releases were captured

- Release record: the lock proxy's `UnlockEvent(toAssetHash, toAddress, amount)`, emitted on every release
  (source: polynetwork/eth-contracts, LockProxy.sol). A zero asset field marks the native coin. The amount is
  the value passed to the token or native transfer.
- Ethereum, ERC-20 (kind `erc20`, 14,580 rows): Transfer logs with the lock proxy as sender, each matched to
  an `UnlockEvent` of the same token in the same transaction. All 14,580 Transfer logs in the window matched,
  and no event was left without a transfer.
- Ethereum, native ETH (kind `native`, 88 rows): from `UnlockEvent` with a zero asset field. The lock proxy
  sends ETH only inside unlock, so the event records every native outflow; no traces were needed.
- BSC, ERC-20 (kind `event`, 102,781 rows): taken from `UnlockEvent` directly. Transfer logs were not fetched
  for BSC because the event carries the token and the transferred amount, and the BSC log volume is large
  (112,579 release events). BSC rows therefore have no transfer-level cross-check.
- BSC, native BNB (kind `native`, 9,798 rows): from `UnlockEvent` with a zero asset field.
- Timestamps: block timestamps returned with each log, on both chains (exact).
- Token symbols and decimals come from the token contracts. All decimals were re-queried once and matched
  the cache, and three BSC symbols that had failed on the first call were re-read.

## Exclusions

- Releases at or after each leg's keeper-key replacement are part of the failure (BSC 09:33:07 UTC,
  Ethereum 09:48:40 UTC; `incidents.csv` notes). Neither leg had a release between its replacement and the
  window end, so nothing was dropped on this rule. The last kept release is at 09:32:07 UTC.
- Transfers to the lock proxies themselves: none.
- Releases to other lock proxies of the same bridge, detected by checking the 60 most frequent recipients
  for the proxy interface: none found.
- Ethereum outflows without a release event (fee forwarding or administrative moves): none in the window.
  On BSC these were not measured, because Transfer logs were not fetched.

## Totals

| measure | Ethereum leg | BSC leg | both |
|---|---|---|---|
| releases | 14,668 | 112,579 | 127,247 |
| priced (count share) | 11,159 (76.1%) | 61,973 (55.0%) | 73,132 (57.5%) |
| USD, priced releases | 1,171.7M | 937.0M | 2,108.7M |
| days with a release | 151 | 150 | 151 |
| median priced release (USD) | 4,110 | 11.5 | 28.6 |
| 99th percentile release (USD) | 2.05M | 0.22M | 0.62M |
| median daily USD (priced) | 3.40M | 2.07M | 5.53M |
| 90th percentile daily USD | 15.0M | 16.1M | 34.6M |

Largest assets by USD:
- Ethereum: USDT 538.0M (2,575), WETH 130.9M (557), WBTC 124.2M (228), USDC 88.5M (287), ETH 57.9M (88),
  FEI 45.8M (218), O3 40.8M (1,325), REVO 27.3M (1,017); 63 other tokens 118.2M.
- BSC: ETH (Binance-Peg) 315.1M (1,724), BUSD 205.4M (34,795), BTCB 161.3M (511), USDC 60.2M (3,346),
  COW 52.7M (1,578), OOE 33.7M (72), O3 28.6M (4,654), pCWS 24.8M (647); 68 other assets 55.0M.

Prices: DefiLlama `/chart` (search window 1,800 s hourly, 43,200 s daily; the helper's default of 600 s
returns sparse 2021 series). 19,783 releases were priced from the token's hourly series within 2 h and 13,371
from its daily series within 36 h. Four issuer-pegged tokens have no DefiLlama series of their own for 2021:
BUSD, USDC and ETH as Binance-Peg tokens on BSC, and pONT, this bridge's 1:1 ONT token on Ethereum.
These 39,978 releases were priced from the underlying coin's series, and the price source in
`raw/E05/rows_with_detail.json` says so for each row. pONT accounts for 23.5M of the Ethereum total. BTCB is
configured the same way but was priced from its own series.

## Unpriced releases (no DefiLlama point within tolerance; amounts in token units)

- Ethereum (3,509 rows): USDT_LP 1,968 rows, 546.8M units; XUSDT 406 rows, 81.9M units; XWBTC 308 rows,
  1,715 units; XWETH 235 rows, 8,873 units; TSX 190; LEV 153; and 31 more tokens, some only partly unpriced.
  USDT_LP is a pool-share token named after USDT (fixed supply of 10^16 units, many independent recipients).
  The X tokens are third-party wrappers ("CROSS FLAMINCOME" wrapped USDT, WBTC and WETH). Their redemption
  value is not established here, so they stay unpriced. Valued at par they would be large: about 0.63B USD
  for USDT_LP and XUSDT together.
- BSC (50,606 rows): HMDX ("Poly-Peg MDX", the bridge's peg of MDX) 39,092 rows, 130.7M units; BUSD_LP 5,557
  rows, 0.10M units; LP-ETH 2,671 rows, 0.24M units; LEV 535; DOG ("Poly-Peg DOG") 455; TSX 332; BOPR 303;
  and 53 more tokens, some only partly unpriced. DefiLlama has no 2021 MDX series under its BSC, HECO or CoinGecko identifiers
  (tried 2026-10-16), so HMDX stays unpriced. At mid-2021 MDX prices of order 1 USD, HMDX would add on the
  order of 0.1B to 0.3B USD; this estimate is not used in the file.

## Extremes

- Largest single release: 13,813.8 WETH (32.4M USD), Ethereum leg, 2021-07-26 13:22:38 UTC.
  The largest on BSC: 12,977.2 ETH (Binance-Peg, 23.8M USD), 2021-06-27 18:18:23 UTC.
- Busiest hour by USD (both legs): 2021-07-26 13:00 UTC, 38 releases, 56.6M. Ethereum alone: the same hour,
  56.0M. BSC alone: 2021-08-06 11:00 UTC, 36.0M.
- Busiest hour by count: 2021-04-08 12:00 UTC, 972 releases (969 on BSC) worth 61,000 USD priced, a batch
  of small releases.
- Busiest day by USD: 2021-07-29, 939 releases, 237.3M (Ethereum 129.7M, BSC 107.5M).
- Busiest day by count: 2021-05-10, 5,528 releases (5,391 on BSC), 8.8M USD priced.

## Gaps

- Block coverage is complete on both legs: release events (and, on Ethereum, Transfer logs) were fetched for
  every block of the window in fixed chunks.
- Longest stretches without a release: Ethereum about 12 h (2021-03-23 17:39 to 2021-03-24 05:32 UTC). BSC
  32 h (2021-03-22 13:46 to 2021-03-23 21:37 UTC) and 25 h at the start of the window. These are quiet
  periods early in the window, not missing data.
- Unpriced value: 23.9% of Ethereum rows and 45.0% of BSC rows, concentrated in the pool-share tokens and
  HMDX listed above. The USD series is a lower bound on the value released.
- Polygon leg not collected (see above).
- BSC has no transfer-level cross-check, and its outflows without a release event were not measured.

## Fitness for a limit

- Ethereum leg: complete in count and timing. 76% of releases are priced, including every release of the
  major assets (USDT, USDC, WETH, ETH, WBTC, FEI, DAI). A limit fitted to the priced series is fitted to
  most of the value, but it understates traffic by the unpriced pool-share releases (USDT_LP, X tokens),
  whose value may be large.
- BSC leg: complete in count and timing, with exact timestamps. Only 55% of rows are priced. Major assets are
  priced through their pegs, but HMDX (35% of releases) and the pool-share tokens are not. The priced series
  supports a limit as a lower bound.
- Combined lock-proxy limit: Ethereum and BSC are both covered, Polygon is missing.
