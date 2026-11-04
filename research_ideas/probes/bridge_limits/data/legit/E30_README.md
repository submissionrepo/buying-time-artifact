# E30: releases from the Ethereum gateway before the failure (August 2024)

File: `E30.csv` (12,079 rows; columns ts_utc, leg, asset, amount, usd, kind, priced).
Scripts: `build_legit.py E30` (collect, reconcile, price, write; figures below come from its
`raw/E30/summary.json`), `read_e30_limits.py` (limit parameters).
Raw caches (addresses and transaction identifiers stay there): `raw/E30/`.

## Window

- 150 days ending one second before the first unauthorized release (2024-08-06T09:37:23Z):
  2024-03-09T09:37:23Z to 2024-08-06T09:37:22Z.
- Ethereum blocks 19,396,689 to 20,468,678 (block times 2024-03-09T09:37:23Z to 2024-08-06T09:37:11Z;
  the next block holds the first unauthorized release).

## Release point

One contract: the bridge's Ethereum gateway (the proxy of the v2/v3 mainchain gateway, the custody leg
`E30_eth` in `onchain_targets.json`). It holds the escrowed assets and releases them on operator
signatures. No other custody contract of this bridge is involved on Ethereum.

## How releases were captured

- Release record: the gateway's `Withdrew(bytes32, Receipt)` event, emitted once per completed release
  (direct release, or unlock of a locked request). One event is one row, kind `event`. The receipt
  in the event gives recipient, token, standard (ERC-20 or ERC-721) and quantity.
- Reconciliation: all ERC-20/ERC-721 `Transfer` logs with the gateway as sender (5,013) and all
  value-bearing calls made by the gateway (`trace_filter`, 7,071) were matched by transaction to a
  release event of the same token.
  - Every token transfer out matched a release event.
  - Native ether: each of the 7,058 WETH-denominated release events was paid out as native ether by the
    gateway in the same transaction (the gateway holds WETH and unwraps it); 7,068 value-bearing calls
    sit in those transactions. The remaining 3 calls (0.0116 ETH each) lie in transactions that
    reverted (receipt status 0, checked one by one), so nothing moved; they are not in the CSV.
  - Hence no `erc20` or `native` rows: the event series is complete for this gateway.
- Locked requests: the gateway emitted no `WithdrawalLocked` or `WithdrawalUnlocked` event in the
  window. Every release in the window passed below the per-token lock threshold.
- Timestamps: block time of the event.
- Deposits into the gateway (28,160 `DepositRequested` events) are inflows and are not used.

## Exclusions

- Movements between the bridge's own addresses: none found (no token transfer or native call from the
  gateway to itself or to a bridge-controlled address outside a release event).
- Releases belonging to the failure: none in the window; both unauthorized releases fall in the next
  block range (from block 20,468,679).
- The three reverted native calls above.

## Totals

| asset | releases | amount | USD at the time |
|---|---:|---:|---:|
| ETH (released from WETH as native ether) | 7,058 | 40,299.78 | 139,991,121 |
| USDC | 2,431 | 23,204,476 | 23,200,127 |
| AXS | 618 | 2,981,487 | 23,113,828 |
| APRS | 926 | 9,267,507 | 9,624,753 |
| SLP | 109 | 1,054,218,830 | 4,847,138 |
| PIXEL | 84 | 10,396,020 | 3,739,271 |
| YGG | 66 | 905,262 | 902,804 |
| BANANA | 60 | 103,855 | 204,091 |
| AGG | 58 | 35,180,172 | unpriced |
| three ERC-721 collections | 669 | 669 items | unpriced |
| **all** | **12,079** | | **205,623,133** |

- Priced: 11,352 of 12,079 rows (94.0%); 11,352 of the 11,413 fungible rows (99.5%). The unpriced
  fungible rows are the 58 AGG releases: DefiLlama returned no hourly or daily price for that token
  in the window. ERC-721 items are left unpriced.
- Prices: DefiLlama `/chart` hourly series, nearest point within 2 h (11,351 rows); daily series within
  36 h (1 row).
- Release size (priced rows): median 627 USD, 90th percentile 12,496, 99th 227,196, 99.9th 2.71M.
- Daily totals (priced, all 150 UTC days): mean 1.36M, median 0.49M, 90th percentile 2.71M, 99th
  11.19M, maximum 13.92M.
- Largest single release: 3,416.68 ETH (12.20M USD) at 2024-03-17T11:59:47Z.
- Busiest hour: 2024-03-17 11:00 UTC, 12.23M USD in 6 releases (the largest release falls in it).
- Busiest day: 2024-06-29, 13.92M USD.
- Per-asset maxima (units): ETH single 3,416.68, day 4,107.06 (2024-06-29); USDC single 1,120,882,
  day 1,888,209 (2024-03-26). Both stay below the daily limits in the table below.

## Gaps

- No interval longer than 6 hours without a release.
- AGG and the ERC-721 items have no USD value; AGG is 58 releases.
- The CSV starts at the window start, not at the gateway's launch; releases that were requested on the
  sidechain before the window but completed inside it are included at completion time.

## Limit parameters in force (`raw/E30/limits_state.json`)

Read by `eth_call` on the gateway at three blocks: the block before the first unauthorized release
(20,468,678), the block before the faulty upgrade (20,468,437, block time 08:48:35 UTC; the upgrade
block 20,468,438 has time 08:48:47 UTC), and the window start (19,396,689).

Per token, in token units, at block 20,468,678 (identical at 20,468,437):

| token | high-tier threshold | lock threshold | daily limit |
|---|---:|---:|---:|
| WETH (ETH) | 1,000 | 4,000 | 4,500 |
| USDC | 1,000,000 | 2,000,000 | 2,500,000 |
| AXS | 100,000 | 400,000 | 500,000 |
| SLP | 300,000,000 | 1,500,000,000 | 2,000,000,000 |
| PIXEL | 100,000,000 | 400,000,000 | 300,000,000 |
| YGG | 1,000,000 | 2,000,000 | 2,000,000 |
| APRS | 10,000,000 | 40,000,000 | 30,000,000 |
| BANANA | 100,000 | 600,000 | 500,000 |
| AGG | 200,000,000 | 800,000,000 | 500,000,000 |

- A release at or above the high-tier threshold needs the high-tier operator vote; at or above the
  lock threshold, or once the day's running total reaches the daily limit, the release is locked for
  manual unlock. The unlock-fee parameter is 10 for every token (the contract's percentage scale is
  1,000,000 = 100%).
- Day counter at block 20,468,678 (units already counted on the current day): WETH 103.43, USDC 16,200.
- Vote parameters: operator threshold 70/100, high-tier threshold 90/100 at all three blocks.
  Minimum vote weight: 1,540 at the window start and at the block before the upgrade; **0** at the
  block before the first unauthorized release. The gateway was not paused at any of the three blocks.
- At the window start, WETH, USDC, AXS, SLP, PIXEL, BANANA and AGG had the same values as above; YGG and
  APRS had all limits at 0 (unset) and were configured during the window. Changes between the three
  blocks were not traced further.

## Fit for a limit

Complete for the gateway: every outflow in 150 days is accounted for by a release event, 99.5% of
fungible releases are priced, and there are no gaps. The series also carries the deployed per-token
thresholds, so a fitted limit can be compared with the one in force.
