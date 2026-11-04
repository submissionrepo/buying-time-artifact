# E50: releases from the NEVM vault before the failure (Syscoin UTXO-NEVM bridge, June 2026)

File: `E50.csv` (127 rows; columns ts_utc, leg, asset, amount, usd, kind, priced).
Scripts: `build_e50.py collect` and `build_e50.py build` (collect, reconcile, price, write; figures below come from
`raw/E50/summary.json`), `check_e50.py` (vault creation, relay transactions, price series; `raw/E50/checks.json`),
`summarize_legit.py E50` (shared summary). Raw caches (addresses and transaction identifiers stay there): `raw/E50/`.

## Window

- 150 days ending one second before the first unauthorized release (2026-06-07T08:19:43Z, NEVM block 934,686):
  2026-01-08T08:19:43Z to 2026-06-07T08:19:42Z.
- Syscoin NEVM blocks 849,410 to 934,685 (block times 2026-01-08T08:21:35Z to 2026-06-07T08:17:00Z; the next
  block holds the first unauthorized release). Block 849,409 has time 08:16:57Z, before the window start.
- The vault was created on 2025-03-16 (block 679,803), so the window is a slice of a longer history.

## Release point

One contract: the bridge's vault on Syscoin NEVM (SyscoinVaultManager, verified source read from the network's
Blockscout explorer and cached as `raw/E50/vault_source.sol`). It holds the pre-allocated native SYS that backs
transfers from the UTXO chain, and it is the contract from which the unauthorized 5,000,000,000 SYS left.
It was identified by role from the research notes (`data/incidents/research/batch_L.json`) and checked on chain:
the relay contract named there is the vault's `trustedRelayerContract` at the window end, and the vault's
`SYSAssetGuid` is 123456, the asset number the post-mortem names.

## How releases were captured

- Release record: `TokenUnfreeze(uint64 indexed assetGuid, address indexed recipient, uint value)`. In the
  verified source the vault releases only in `processTransaction`, which only the relay contract may call after
  it has checked an SPV proof of a burn on the UTXO chain. The vault pays native SYS with a plain call
  (`_withdrawSYS`) or ERC-20/721/1155 tokens with token transfers, and emits the event after the payment.
  The contract has no other path for value to leave: no owner withdrawal, no receive or fallback function.
  One event is one row, kind `event`. The event value is in 8-decimal units; a native release pays
  value x 10^10 wei, so the amount in SYS is value / 10^8.
- All 127 releases in the window are native SYS (asset 123456). The vault's registry holds four other assets
  (one ERC-1155 and three ERC-20), but none of them was released in the window.
- Native outflows: checked against the explorer's internal transactions of the vault. In the window the vault
  made 127 successful value-bearing calls; each matches one `TokenUnfreeze` in the same transaction (recipient
  and value x 10^10 wei), and no event lacks its call. All value-bearing calls from the vault in the window
  succeeded.
- Relay check: the relay contract received 162 relay transactions in the window. 128 succeeded: 127 carried
  exactly one release each, and one ended with the relay's own error-code event without calling the vault.
  The other 34 reverted. No release came from a transaction other than a successful relay transaction.
- Balance check: the vault held 9,959,923,830.61 SYS at block 849,409 and 9,947,044,094.74 SYS at block
  934,685. Native locks in the window (the call values of the 49 successful lock transactions for SYS,
  1,336,222.44 SYS) minus the 127 releases (14,215,958.31 SYS) account for the change exactly (residual 0).
  The end balance equals the balance the research notes read at block 934,685.
- Timestamps: block time of the event (exact).

## Exclusions

- Movements between the bridge's own addresses: none. No release went to the vault itself, the relay contract
  or the vault owner.
- Releases belonging to the failure: none in the window. The failure's single release is in block 934,686,
  after the window. The initiating address received no release in the window; its preparatory transfers
  (2,000 SYS on 06-06 and two custom assets on 06-07) were locks into the vault, which are inflows.
- Locks (`TokenFreeze`, 51 in the window: 49 of native SYS and the two custom-asset locks above) and asset
  registrations (2) are not releases.

## Pricing

DefiLlama `/chart` series for `coingecko:syscoin` (the NEVM gas coin is SYS): hourly, nearest point within 2 h.
All 127 releases were priced from the hourly series. The series falls from about 0.020 USD per SYS on
2026-01-10 to 0.0111 on 03-01, 0.0089 on 05-01 and 0.0018 on 06-06 and 06-07 (daily means of the hourly
points). The research notes quote CoinGecko daily prices of 0.00196 (06-06) and 0.00168 (06-07); the hourly
series lies between them.

## Totals

| | |
|---|---|
| Releases | 127, all native SYS, to 44 distinct recipients |
| Amount | 14,215,958.31 SYS |
| USD at the time | 51,717 |
| Share priced | 100% (127 of 127) |
| First / last release | 2026-01-23T20:20:48Z / 2026-06-07T04:40:35Z |
| Days with a release | 43 of the 151 calendar days in the window |
| Release size (USD) | median 29.6, 90th percentile 651, 99th 6,430 (summary script); median 9,000 SYS |
| Daily USD | median 0, 90th percentile 710, maximum 10,262; mean over 150 days 345 |

- Largest single release: 3,000,537 SYS (8,502 USD) at 2026-05-27T05:07:35Z. Next: 1,662,334.8 SYS (6,430 USD,
  2026-05-21) and 549,992 SYS (4,822 USD, 2026-04-30).
- Busiest hour by USD: 2026-05-27 05:00 UTC, 8,502 USD (the largest release alone). By count:
  2026-01-30 23:00 UTC, 6 releases worth 0.04 USD.
- Busiest day by USD: 2026-05-27, 10,262 USD in 8 releases. By count: 2026-06-05, 9 releases (2,383 USD).
- Largest value released in any interval of length 10 min / 1 h / 6 h / 24 h: 8,502 / 9,263 / 10,754 /
  12,656 USD.
- Recipients: the largest recipient took 21% of the SYS released (17 releases); the top five took 67%.
- Time profile: the last 30 days before the failure hold 86 of the 127 releases and 44,491 USD (86% of the
  value). The 90 days from t_fail - 120 d to t_fail - 30 d hold 28 releases worth 7,223 USD; the first 30 days
  hold 13 releases worth 3 USD.

## Gaps

- No block gaps: the vault's logs were read for every block of the window.
- Traffic is sparse. No release in the first 15.5 days of the window (until 2026-01-23). Longest pauses after
  that: 25.1 days (2026-03-05 to 03-30), 14.3 days (02-03 to 02-18), 9.3 days (05-04 to 05-13), and seven more
  between 2 and 8 days.
- Many releases are tiny: 44 are below 1 USD and 77 below 100 USD. USD values are written with two decimals,
  so 25 rows show 0.00 (they are priced; the analysis drops zero values).
- Public volume figures: no published volume series for this bridge was found. The checks above are against
  the chain itself (relay transactions, internal calls, vault balance) and against the vault balance in the
  research notes.

## Fit for a limit

Complete for the vault: every release in 150 days is recorded, matched to its native payment and reconciled
to the vault's balance, and every release is priced. The series is thin, though: 127 releases worth 51,717 USD,
of which 86% fell in the last 30 days, and the 90-day fit window of the replay holds 28 releases worth about
7,200 USD. A limit fitted to this traffic is well defined but rests on few releases; against it, the failure's
5,000,000,000 SYS (notional 9.4 million USD) is three orders of magnitude above the largest legitimate day.
