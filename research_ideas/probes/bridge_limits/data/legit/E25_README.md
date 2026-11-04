# E25 legitimate release history (Ethereum vault, 150 days before the failure)

File: `E25.csv` (one row per release; columns ts_utc, leg, asset, amount, usd, kind, priced).
Script: `collect_legit_E05_E25.py E25` (raw RPC and price caches under `raw/E25/`; numbers below from
`raw/E25/summary.json`).

## Window and contracts

- Failure time: 2023-12-31 20:52:47 UTC, the first unauthorized release (30.095 ETH) under the corrected
  selection in `results/incidents.csv` notes. The `first_release_utc` column there (21:07:59) is the first
  large release; using the earlier time is the conservative choice.
- Window: 2023-08-03 20:52:47 UTC to 2023-12-31 20:52:46 UTC (150 days ending one second before the failure).
- Chain: Ethereum, blocks 17,836,972 to 18,907,960 (the block before the first unauthorized release).
- Release point: the bridge's Ethereum vault contract (the single custody contract for E25 in
  `data/incidents/onchain_targets.json`). It is the only leg of this failure.

## How releases were captured

- Release record: the vault's own `Withdraw` event (source: orbit-chain/bridge-contract, EthVault.impl.sol);
  the amount is the first entry of the event's integer array and a zero token field marks the native coin.
  4,211 events in the window.
- ERC-20 releases: Transfer logs with the vault as sender. Every one of the 2,480 such logs in the window sits
  in a transaction that also carries a `Withdraw` event. 2,359 match the event's token directly. The other 121
  match on transaction and identical amount, but the event names a different token address from the one
  transferred (two tokens the vault maps to newer contracts). These rows record the token actually
  transferred.
- Native (ETH) releases: from `Withdraw` events with a zero token field (1,731 events). The native outflows
  were checked against call traces (`trace_filter`, value-bearing calls from the vault) over the first
  194,000 blocks of the window (2023-08-03 to about 2023-08-30). In that range the 285 native release events
  and the 285 native transfers in release transactions are identical in transaction and amount. Traces were
  not fetched for the rest of the window; the event series is complete on its own because the vault emits
  `Withdraw` on every native release.
- Timestamps: block timestamps returned with each log (exact).

## Exclusions

- Everything at or after the failure time (the six unauthorized releases and the preliminary 30.095 ETH
  release) lies outside the window.
- Native outflows from the vault in transactions without a `Withdraw` event: 44 in the trace-checked range,
  632.5 ETH in total. They are administrative movements, not releases to users, and are excluded. Such
  movements in the remaining 120 days were not measured because traces were not fetched there; they would
  not be releases either.
- Movements to the vault itself or to other bridge contracts: none found. The recipient check that detects
  the bridge's own proxies found none (it is designed for the E05 lock proxies and does not apply here).
- Kept: the 0.012 WBTC withdrawal at 20:40:35 UTC on the failure day is a legitimate release (its message
  was later reused at an inflated amount) and is the last row of the file.

## Totals

| measure | value |
|---|---|
| releases | 4,211 (ERC-20 2,480; native 1,731; event-only 0) |
| priced | 4,153 (98.6% by count) |
| USD, priced releases | 46.92M |
| days with at least one release | 151 of 151 calendar days touched by the window |
| median release | about 1,050 USD; 99th percentile about 170,000 USD |
| median daily USD | about 151,000; 90th percentile about 651,000 |

By asset (USD): USDT 22.58M (850), ETH 12.51M (1,731), USDC 5.39M (299), ORC 3.27M (328),
WBTC 1.59M (96), DAI 0.77M (47), the remaining 20 tokens together 0.81M.

Prices: DefiLlama `/chart` (search window 1,800 s hourly, 43,200 s daily), hourly series within 2 h for
4,065 releases, daily series within 36 h for 88. Unpriced: 58 releases in seven small tokens with no DefiLlama
point near the release (PACE 31 of 37, RUSH 13, FIT 7, TRIX 3 of 7, TOM 2, DON 1, UNM 1). Judging by the priced amounts of the same tokens, their value is
negligible next to the total.

## Extremes

- Largest single release: 1,757,054 USDT (about 1.756M USD), 2023-09-06 05:11:35 UTC.
- Busiest hour by USD: 2023-09-06 05:00 UTC, 1.756M (that single release). Next: 2023-10-17 23:00 UTC,
  1.32M.
- Busiest hour by count: 2023-09-19 02:00 UTC, 59 releases, 0.56M USD.
- Busiest day by USD and by count: 2023-09-18, 302 releases, 4.69M USD.

## Gaps

- No missing block ranges: release events and Transfer logs were fetched for the full block range in fixed
  5,000-block chunks.
- Longest stretches without a release are about 12 to 15 hours (for example 2023-12-16 11:44 to
  2023-12-17 02:19 UTC). These are quiet hours, not missing data.
- 1.4% of releases (by count) are unpriced, as listed above.
- Native non-release movements are measured only in the first 194,000 blocks (see Exclusions).

## Fitness for a limit

The series is complete for releases from the vault over the full 150 days and is priced for 98.6% of rows,
covering essentially all value. It supports fitting hourly and daily limits to this vault's own traffic.
