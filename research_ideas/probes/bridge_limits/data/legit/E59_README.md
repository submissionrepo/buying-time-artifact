# E59: releases from the USDC custody contract before the failure (AFX bridge, Arbitrum, July 2026)

File: `E59.csv` (2,464 rows; columns ts_utc, leg, asset, amount, usd, kind, priced). Built 2026-10-16.
Script: `build_e59.py collect`, `build_e59.py scan`, `build_e59.py build` (figures below come from its
`raw/E59/summary.json` and from `E59.csv`). Raw caches (addresses and transaction identifiers stay there): `raw/E59/`.

## Window

- 150 days ending one second before the first unauthorized release (2026-07-22T21:30:25Z, Arbitrum block
  486,658,838): 2026-02-22T21:30:25Z to 2026-07-22T21:30:24Z.
- Arbitrum blocks 434,909,884 to 486,658,834 (block times 2026-02-22T21:30:25Z and 2026-07-22T21:30:24Z). Block
  486,658,835 is the first with the failure's timestamp.
- The contract was deployed inside the window: its code first appears in block 462,020,319 (2026-05-12T10:27:45Z).
  The history therefore starts at deployment and covers 71.5 of the 150 days (2026-05-12T10:27:45Z to
  2026-07-22T21:30:24Z). The research notes (`data/incidents/research/batch_G.json`) and the DefiLlama record of
  the bridge (listed from 2026-06-11; cached as `raw/E59/defillama_protocol_afx-bridge.json`) name no earlier
  custody contract.

## Release point

One contract: the bridge's USDC custody contract on Arbitrum (`raw/E59/targets.json`, taken from the research notes
and checked on chain). It holds the deposited USDC and pays a withdrawal after validator signatures and a dispute
period. The failure's single release of 24,150,000 USDC left from it.

## How releases were captured

- Release record: `FinalizedWithdrawal(address indexed user, address destination, uint64 usd, uint64 nonce,
  bytes32 message)`. The signature is that of the same event in Hyperliquid's Bridge2 (reference source cached as
  `raw/E59/ref_hyperliquid_Bridge2.sol`), where finalization transfers `usd` USDC units to `destination` and then
  emits the event. The contract emitted 2,464 of them in the window.
- Rows: the USDC Transfer logs with the contract as sender, each matched to a FinalizedWithdrawal in the same
  transaction with the same destination and amount (kind `erc20`). All 2,464 transfers matched an event and all
  2,464 events matched a transfer. Every release is native USDC; the bridged USDC (USDC.e) never moved.
- Requests: the contract emitted 2,465 withdrawal-request events (Bridge2's field layout; the topic differs from
  Bridge2's, so the name or a type differs). Every finalization has its request. The one request not finalized in
  the window is the failure's own (block 486,657,995, 24,150,000 USDC to the failure's recipient), finalized in the
  failure block.
- Other events move nothing: 28,392 FailedWithdrawal events (14,783 with code 0, 13,597 with code 1, 12 with code
  3; in Bridge2 these codes mean request already made, already finalized, and dispute period not over), and 252
  events of a fourth type carrying an address, an amount and a code (all code 1), none in a transaction that moved
  USDC.
- Timestamps: block time of the transfer (block headers).

## Reconciliation and completeness

- No block gaps: the contract's logs and the USDC transfers in and out were read for every block from deployment
  to the window end (25 chunks of 1,000,000 blocks).
- Topic scan of Transfer logs with the contract as sender, any token, over the same blocks (30,000-block steps):
  2,465 logs. 2,464 are the USDC logs above (the same logs as the address-filtered collection, none missing on
  either side). The other is a log of a token named TWBC (1,133,689 units) in a transaction that an unrelated
  account sent to that token's contract, which emitted 60 Transfer logs naming various senders. The contract held
  none of that token before the block, emitted no log and moved no USDC in that transaction, so nothing left it.
  Not a release.
- USDC balance: 0 at block 462,020,318 (before deployment) and 24,187,765.359816 at block 486,658,834. Logged
  inflows (8,970 transfers, 26,922,140.503016 USDC) minus logged outflows (2,464 transfers, 2,734,375.1432 USDC)
  account for the change exactly (residual 0). The failure's 24.15M was 99.8% of the end balance.
- Native ether: balance 0 at both ends and at all 25 chunk boundaries. The public endpoints offer no trace API for
  Arbitrum, so internal ether movements are bounded by these balances only; the contract pays withdrawals in USDC.
- Requests and finalizations pair up as described above; the only unpaired request is the failure's.

## Exclusions

- Movements to the contract itself: none.
- Releases belonging to the failure: none in the window. The failure's request lies in the window but moved
  nothing; its release is in block 486,658,838. No release in the window went to the failure's recipient.
- Deposits (8,970 USDC transfers into the contract) are inflows and are not used.

## Pricing

DefiLlama `/chart` series of native USDC on Arbitrum: all 2,464 rows priced from the hourly series, nearest point
within 2 h. The price per USDC ranges from 0.9984 to 1.0021 USD.

## Totals

| | |
|---|---|
| Releases | 2,464, all native USDC, to 1,623 distinct recipients |
| Amount | 2,734,375.14 USDC |
| USD at the time | 2,733,857 |
| Share priced | 100% of rows and of value (2,464 of 2,464) |
| First / last release | 2026-05-12T12:40:44Z / 2026-07-22T20:47:10Z |
| Days with a release | 69 of the 72 calendar days from deployment to the failure |
| Release size (USD) | median 50.20, 90th percentile 2,499, 99th 18,069, 99.9th 54,021 |
| Daily USD over the 150 days | mean 18,226; median 0; 90th percentile 58,136; 99th 213,224; maximum 240,130 |
| Daily USD over the 71.5 days since deployment | mean 38,257; median 16,450; 90th percentile 89,143; maximum 240,130 |

- Largest single release: 116,114.53 USDC (116,090 USD) at 2026-07-20T12:19:44Z. Next: 70,230.87 USDC
  (2026-06-22), 57,500.36 (2026-07-22) and 50,000.00 (2026-06-24).
- Busiest hour by USD: 2026-07-20 12:00 UTC, 126,451 USD in 5 releases. By count: 2026-06-29 11:00 UTC, 47
  releases (631 USD).
- Busiest day by USD: 2026-07-22 (the failure day, up to 21:30:24), 240,130 USD in 52 releases. By count:
  2026-06-29, 455 releases (17,372 USD).
- Largest value released in any interval of length 10 min / 1 h / 6 h / 24 h: 116,384 / 126,482 / 177,730 /
  328,691 USD.
- Recipients: the largest recipient took 6.6% of the USD, the top ten 31.4%.
- Time profile: the last 30 days before the failure hold 1,747 releases and 1.82M USD (66.6% of the value).

## Gaps

- No block gaps: the contract's logs and the USDC transfers were read for every block from deployment to the
  window end, and the any-token scan covers the same range.
- No release before 2026-05-12: the contract did not exist for the first 78.5 days of the window.
- After deployment, one pause longer than two days: 82.7 hours (2026-05-15T09:55Z to 2026-05-18T20:35Z). 30 pauses
  longer than 6 hours, all but one in May and June, most of them spanning the UTC night.
- No unpriced rows.

## Script changes (2026-10-16)

The method in `build_e59.py` held on chain (event signature, release path, balances). The collection had stopped at
block 483,020,318 and was resumed to the window end (block 486,658,834). Added to the build after the first run: the
comparison of the scan's USDC logs with the address-filtered collection, the check of the other-token log
(transaction and the contract's balance of that token, cached as `raw/E59/other_token_checks.json`), and the pairing
of withdrawal requests with finalizations.

## Fit for a limit

Complete for the custody contract: every outflow from deployment to the failure is a finalized withdrawal, matched
to its event, reconciled to the USDC balance, and priced. The series covers 71.5 days, not 150, so a fit window of
90 days or more holds at most 71.5 days of traffic, and any fit window that starts before 2026-05-12 includes days
on which no release was possible. Against this traffic, the failure's 24.15M USDC is about 100 times the largest
legitimate day (240,130 USD) and 208 times the largest single release.
