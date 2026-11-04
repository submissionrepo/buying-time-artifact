# E22: releases from the three Ethereum custody legs before the failure

File: `E22.csv` (8,527 rows; columns ts_utc, leg, asset, amount, usd, kind, priced).
Scripts: `collect_legit_E22_E24.py` (collect, price, write), `stats_E22_E24.py` (figures below).
Raw caches (addresses and transaction identifiers stay there): `raw/E22/`.

## Window

- 150 days ending one second before the first unauthorized release (2023-07-06T18:10:35Z):
  2023-02-06T18:10:35Z to 2023-07-06T18:10:34Z.
- Ethereum blocks 16,571,452 to 17,636,490 (the next block holds the first unauthorized release).

## Release points

Three custody accounts on Ethereum, one per bridge leg in `onchain_targets.json`
(the `E22_eth_ftm_tests` entry is the same Fantom custody in an earlier sub-window, so it is not a
separate leg; its recipients are used only for the exclusions below):

| leg | role | releases | USD priced |
|---|---|---:|---:|
| fantom | custody of the Fantom bridge (threshold-signature controlled account) | 7,135 | 204,078,636 |
| moonriver | custody of the Moonriver bridge (same design) | 899 | 23,528,158 |
| dogechain | custody of the Dogechain bridge (same design) | 493 | 1,677,997 |

The custody accounts are externally owned accounts controlled by the operator's threshold-signature
scheme. A release is a direct transfer signed by that account; the accounts emit no release events.

## How releases were captured

- ERC-20: every `Transfer` log with the custody account as sender, across all token contracts
  (`eth_getLogs`, 5,000-block steps).
- Native ether: `trace_filter` with the custody account as caller; calls with value above zero,
  call type `call`, no error, and not inside a transaction whose top-level call reverted.
  Kind `native` rows (516) come from these traces. The Fantom leg sent no native ether in the window;
  it released wrapped ether (WETH, 1,723 releases) as an ERC-20.
- Timestamps: block time of the log or trace.

## Exclusions

- Transfers between the three custody accounts: none found.
- Releases belonging to the failure: one 2-USD transfer on the day of the failure to a recipient of
  the failure's outflows (Fantom leg) was dropped. All large unauthorized releases fall after the
  window end.
- 159 ERC-20 `Transfer` events with a custody account as sender that occur in transactions where the
  custody account made no call (139 Dogechain, 14 Moonriver, 6 Fantom): third-party `transferFrom`
  or unsolicited token events, not releases by the bridge.
- Other addresses of the operator could not be identified from the inputs. Recipients are dispersed
  (4,169 distinct); the top 20 recipients take 47.9% of priced USD and the largest one 11.3%.
  Five of the top 20 are contracts (14.1% of priced USD); none could be attributed to the operator,
  so they stay in.

## Pricing

DefiLlama `coins/batchHistorical` at each release time: first with a 10-minute search width,
then a 2-hour width for misses (price timestamp within 2 hours of the release). Rows without a price
in that range are left unpriced (`priced = no`, empty `usd`). Prices are those of the time, so the
USDC releases of 2023-03-11/12 carry the depeg price.

## Totals

- Releases: 8,527 (8,011 ERC-20, 516 native); releases on all 151 calendar days touched by the window.
- Priced: 8,441 of 8,527 (98.99%); priced USD 229,284,791.
- Unpriced (86 rows, token amounts, not in the USD total): FONT 24 rows, MODA 22, PPBLZ 13, ARCHA 8,
  USDC 4 (28,316 USDC in total), WSTA 4, VBTC 3 (0.30 units), METRIC 2, PAR 2, KEK 1, ICE 1,
  WOOFY 1, vETH 1 (3.25 units). Apart from the USDC, VBTC and vETH rows these are small-cap tokens.
- Single release (priced): median 1,848 USD; 99th percentile 499,498 USD.
- Daily priced USD: median 539,495; mean 1,518,442; 90th percentile 2,822,171; no day without a release.

## Peaks

- Largest single release: 9,998,000 USD (USDC, Fantom leg, 2023-04-04 05:09:35 UTC).
- Busiest hour by USD: 2023-03-12 00:00 UTC, 11,127,402 USD in 8 releases.
  Busiest hour by count: 2023-05-24 13:00 UTC, 69 releases.
- Busiest day by USD: 2023-03-11, 31,162,566 USD in 289 releases (the USDC depeg day).
  Busiest day by count: 2023-05-24, 356 releases and 19,045,848 USD, after three days of 30 to 49
  releases a day. `incidents.csv` records degraded service from late May 2023; the burst is
  consistent with a backlog being released, which these data do not verify.

## Gaps and caveats

- Coverage is continuous: the longest pause between consecutive releases across the three legs is
  12.6 hours (Fantom leg, ending 2023-04-13). On the smaller legs the longest pauses are 6.6 days
  (Dogechain) and 2.9 days (Moonriver).
- Traffic falls in the last four weeks (about 190 releases a week, against about 400 a week from
  February to mid-May), consistent with
  the degraded service noted above; a limit fitted to the full window mixes normal and degraded
  operation.
- Releases to operator-controlled addresses other than the three custody accounts (rebalancing to
  other chains' custody or routers) cannot be ruled out; see Exclusions.
- 1.0% of releases are unpriced.
