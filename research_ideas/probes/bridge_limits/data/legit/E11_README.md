# E11: legitimate releases of the token bridge's Ethereum escrow before the failure

`E11.csv` lists every release from the token bridge's Ethereum escrow in the 150 days that end one second
before the first unauthorized release on Ethereum (2022-02-02T18:24:13Z, `results/incidents.csv`). One row
per release: `ts_utc, leg, asset, amount, usd, kind, priced`. Built by `collect_e11.py` (Transfer and WETH
Withdrawal logs), `collect_e11_traces.py` (native-value calls, for the check) and `build_e11.py`;
`reconcile_e11.py` checks balances; `summarize_legit.py E11` gives the summary numbers below. Price sources
per asset are in `E11_prices.csv`; checks in `raw/E11/stats.json`, `raw/E11/reconcile.json`,
`raw/E11/summary.json`.

## Contracts and window

| Role | Use |
|---|---|
| Token bridge escrow on Ethereum (the release point; one custody contract) | Transfer logs with it as sender; native-value calls from it (traces) |
| WETH contract | Withdrawal logs with the escrow as source (native ETH payouts) |

- Chain: Ethereum. Window 2021-09-05T18:24:13Z to 2022-02-02T18:24:12Z, blocks 13,167,287 to 14,128,212
  (the first unauthorized release is in block 14,128,223). 193 log chunks and 97 trace chunks, no gaps.
- Bridge logic: `ethereum/contracts/bridge/Bridge.sol` at commit 608c724 (cached as
  `raw/E11/Bridge_608c724.sol`). Only tokens native to Ethereum are held in escrow; assets native to other
  chains are minted and burned, so they are outside the escrow leg.
- The escrow held none of the twelve largest assets at the window start (balances 0) and its first release
  is on 2021-09-15, so the window covers the escrow's whole operating history up to the failure.

## How releases were captured

- **ERC20 (kind `erc20`).** Transfer logs with the escrow as sender (payouts of `completeTransfer` to the
  recipient and, where set, the relayer fee).
- **Native ETH (kind `native`).** In this version the bridge emits no release event of its own.
  `completeTransferAndUnwrapETH` unwraps WETH and then sends ETH, so each payout appears as a WETH
  Withdrawal log with the escrow as source; one row per Withdrawal log. Checked against `trace_filter`
  over the whole window: in all 3,012 transactions with a native payout the traced ETH sent equals the
  WETH withdrawn; no traced payout lacks a Withdrawal log.
- **Balance check.** For the twelve largest assets (USDC, USDT, HUSD, BUSD, WETH, DAI, wstETH, FRAX,
  FTX Token, SRM, and the unpriced bETH and HBTC), balance at the window end minus the start equals logged
  inflows minus logged outflows exactly (residual 0 for each).

## Exclusions

- Transfers to the zero address: 2,955 (burns of wrapped assets on outbound transfers, not releases).
- Transfers to the escrow itself: 0. No other address of the bridge holds escrow on Ethereum.
- Native calls that are not payouts: WETH deposits by the escrow (`wrapAndTransferETH`, inflows) and 52
  dust refunds inside outbound transfers (2.7e-7 ETH in total).
- Failure: the three unauthorized releases (93,750 ETH) fall after the window; no row in the window goes to
  the failure's recipient (0 rows).

## Prices

DefiLlama coins API, in this order: hourly chart (`/chart`, 2 h tolerance) for assets above 1M USD on a daily
pass; `batchHistorical` at the middle of the release hour (2 h tolerance); daily chart (36 h tolerance) as
the last resort. The chart endpoint is sparse for late 2021 (one empty 500-hour block for ETH), which the
point pass fills. MATIC, USDK and ibBTC have no series under the contract key and are valued with their
CoinGecko-id series (contracts matched in full). Priced releases: 3,590 hourly, 4,089 point, 2 daily.
Implied prices more than 3x away from an asset's median: 51 rows, 0.37 million USD (SRM, PIXEL, ORION).

## Totals

| | |
|---|---|
| Releases | 7,987 in 7,983 transactions (4,975 ERC20, 3,012 native ETH) |
| Assets | 141 |
| USD (priced rows) | 775.39 million (ERC20 584.36M, native ETH 191.02M) |
| Share priced | 96.2 % of releases (7,681) |
| First / last release | 2021-09-15T17:24:43Z / 2022-02-02T17:53:39Z |
| Days with a release | 140 of the 141 days from the first release to the window end |
| Per release (priced) | median 7,058 USD, p90 220,895 USD, p99 1.61 million USD |
| Per day (days with releases) | median 4.07 million USD, p90 12.01 million, max 23.10 million; mean over 150 days 5.17 million |

Largest assets by USD: ETH 191.0M, USDC 159.1M, USDT 139.3M, HUSD 41.9M, BUSD 37.3M, WETH 36.9M, DAI 23.4M,
wstETH 22.8M, FRAX 22.5M.

- **Largest priced release:** 9,301,006 USDT, 9.30 million USD, 2022-01-16T09:15:54Z. Next: 8,651,052 USDC
  (8.66M, 2021-11-12) and 6,214,935 HUSD (6.20M, 2021-09-20). Largest native ETH release: 1,319.4 ETH
  (5.09M, 2022-01-04).
- **Largest release overall (unpriced):** 43,781.4 bETH on 2022-01-29T03:27:25Z, a `completeTransfer`
  redeemed by its own recipient. At ETH parity it would be about 111.6 million USD, twelve times the largest
  priced release. It is left unpriced because DefiLlama has no series for bETH.
- **Busiest hour (priced):** 2021-11-12T22:00Z, 9.59 million USD. By count: 2022-01-12T04:00Z, 22 releases.
- **Busiest day (priced):** 2021-10-08, 23.10 million USD. By count: 2022-01-12, 207 releases. With bETH at
  ETH parity, 2022-01-29 would be the busiest day by far.

## Gaps

- 306 releases (3.8 %) unpriced in 32 assets. Two matter: bETH (142 releases, 46,201 bETH, about 117.7
  million USD at ETH parity) and HBTC (27 releases, 110.8 HBTC, about 5.3 million USD at BTC parity). The
  parity figures are indicative only and are not in the CSV. The other 30 assets are small (PIXEL 54 releases
  in hours the series misses, RAY 14, 1SOL 10, WWT 10, others below 10).
- The priced USD total therefore understates the escrow's release volume by about 16 % (123 million USD at
  parity against 775 million priced). bETH releases start on 2022-01-26, so the shortfall sits in the last
  eight days of the window.
- No block gaps; no silent stretch above two days after the first release.
