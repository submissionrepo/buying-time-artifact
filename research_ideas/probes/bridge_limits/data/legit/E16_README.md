# E16: legitimate releases of the BSC Token Hub before the failure

`E16.csv` lists every release by the hub contract on BSC in the 150 days that end one second before the first
unauthorized release (2022-10-06T18:26:46Z, `results/incidents.csv`). One row per release: `ts_utc, leg,
asset, amount, usd, kind, priced`. Built by `collect_e16.py` (raw logs) and `build_e16.py` (rows, prices,
checks); `summarize_legit.py E16` gives the summary numbers below. Price sources per asset are in
`E16_prices.csv`. Checks are in `raw/E16/stats.json` and `raw/E16/summary.json`.

## Contracts and window

| Role | Use |
|---|---|
| Token Hub (BSC system contract; the release point) | all of its event logs; BEP20 Transfer logs naming it as sender |
| BEP20 token contracts | Transfer logs with the hub as sender, kept only when matched to a hub event |

- Chain: BSC. Window 2022-05-09T18:26:46Z to 2022-10-06T18:26:45Z, blocks 17,660,830 to 21,957,792
  (the next block, 21,957,793, carries the first unauthorized release). 215 block chunks, no block gaps.
- Hub logic: bsc-genesis-contract `TokenHub.sol` at commit a745ecc (cached as `raw/E16/TokenHub_a745ecc.sol`).

## How releases were captured

- **Native BNB (kind `event`).** The hub pays BNB with a plain call and emits `transferInSuccess(bep20Addr,
  recipient, amount)` only after the call succeeded. Rows are those events with `bep20Addr = 0`, plus
  `refundSuccess` with `bep20Addr = 0` (refunds of failed outbound transfers). No trace data was needed:
  the hub emits an event for every BNB payout path in this version.
- **BEP20 tokens (kind `erc20`).** Transfer logs with the hub as sender, matched one to one with a
  `transferInSuccess` or `refundSuccess` event in the same transaction (token, recipient, amount).
  27,693 of 27,693 hub BEP20 events have a matching Transfer log (none unmatched).
- **Completeness check, BNB.** Hub BNB balance at the window end minus the start equals logged inflows
  (`transferOutSuccess` amounts and relay fees, `receiveDeposit`) minus logged outflows (`transferInSuccess`,
  `refundSuccess`, `rewardTo`) exactly: residual 0.000 BNB on a balance of about 154 million BNB.

## Exclusions

- `rewardTo`: relay fee payouts from the hub to the relayer incentive system contract (604,199 events,
  2,416.8 BNB in total). System-internal, not a release to a user.
- BEP20 Transfer logs that name the hub as sender but have no hub event: 345,966 logs, all from token
  contracts that never appear in any hub event in the window (mass airdrop logs emitted by the token
  contract itself; they move nothing out of the hub's custody).
- Transfer logs to the hub itself, the zero address or other system contracts: 2.
- Failure: the failure's two releases (1,000,000 BNB each) fall after the window. A check against the
  failure's recipient found no earlier row to exclude (0 rows).

## Prices

DefiLlama coins API, in this order: hourly chart (`/chart`, 2 h tolerance) for assets above 1M USD on a daily
pass; `batchHistorical` at the middle of the release hour (2 h tolerance); daily chart (36 h tolerance) as
the last resort. Releases with no point within tolerance stay unpriced. DefiLlama has no series under the
contract key for five 1:1 pegged tokens (ETH, DAI, BUSD, USDT, USDC on BSC); these are valued with the
CoinGecko-id series of the underlying asset (contracts matched in full). Priced releases: 586,587 hourly,
6,221 point, 7,428 daily. Implied prices more than 3x away from an asset's median: UST rows in May 2022 (the
depeg, 80 thousand USD) and a few BTCST rows (56 USD).

## Totals

| | |
|---|---|
| Releases | 601,249 (573,556 BNB events, 27,693 BEP20) |
| Legs | hub transfer-in 601,177; hub refund 72 |
| Assets | 78 |
| USD (priced rows) | 408.39 million |
| Share priced | 99.83 % of releases (600,236); BNB 100 % |
| First / last release | 2022-05-09T18:28:13Z / 2022-10-06T18:22:49Z |
| Days with a release | 151 of 151 calendar days |
| Per release (priced) | median 43 USD, p90 500 USD, p99 4,920 USD |
| Per day | median 1.68 million USD, p90 4.07 million, max 27.15 million; mean over 150 days 2.72 million |

Largest assets by USD: BNB 346.6M, BUSD 31.0M, BTCB 9.5M, USDT 6.1M, ETH 5.3M, TWT 3.2M.

- **Largest single release:** 74,000 BNB, 21.49 million USD, 2022-06-09T14:33:55Z (hub transfer-in).
  The next largest are 70,000 BNB (18.6M, 2022-07-23) and 33,870 BNB (10.1M, 2022-05-19).
- **Busiest hour:** 2022-05-19T08:00Z, 25.11 million USD. By count: 2022-05-14T11:00Z, 1,121 releases.
- **Busiest day:** 2022-05-19, 27.15 million USD. By count: 2022-05-14, 14,504 releases.

## Gaps

- 1,013 releases (0.17 %) unpriced, in 29 small BEP20 assets (largest counts: PHB 201, ETC 92, an asset with
  an unreadable symbol 87, ARN 72, EQL 69). Their quantities are in the CSV.
- No block gaps and no silent stretch above two days.
- The series is the hub's own ledger of releases. It does not say which recipients are exchanges or
  operators of the hub; no exclusion by recipient type was made.
