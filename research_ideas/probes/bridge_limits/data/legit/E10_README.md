# E10: releases by the BSC bridge handler before the failure (QBridge, Ethereum to BSC, January 2022)

File: `E10.csv` (64 rows; columns ts_utc, leg, asset, amount, usd, kind, priced). Built 2026-10-16.
Script: `build_e10.py` with steps `bsc`, `eth`, `scan`, `txs`, `build` (figures below come from its
`raw/E10/summary.json` and from `E10.csv`). Raw caches (addresses and transaction identifiers stay there; the
per-proposal record is `raw/E10/executed_detail.json`): `raw/E10/`.

## Window

- 150 days ending one second before the first unauthorized release (2022-01-27T21:36:32Z, BSC block 14,742,022):
  2021-08-30T21:36:32Z to 2022-01-27T21:36:31Z.
- BSC blocks 10,489,797 to 14,742,021 (block times 2021-08-30T21:36:32Z and 2022-01-27T21:36:29Z; the next block
  holds the first unauthorized release).
- The BSC bridge was deployed inside the window, in block 12,884,374 (2021-11-23T07:38:34Z). The history therefore
  starts at the deployment and covers 65.6 of the 150 days (2021-11-23T07:38:34Z to 2022-01-27T21:36:31Z); no
  release was possible before it.
- Origin side: Ethereum blocks 13,663,216 to 14,090,184 (2021-11-22T07:38:35Z to 2022-01-27T21:36:27Z), which hold
  every deposit of the Ethereum bridge from its deployment (2021-11-29) to the failure.

## Release point

The BSC side of the bridge: the bridge contract (a proxy) executes proposals relayed from Ethereum, and its handler
mints the wrapped ether token xETH. The failure's unauthorized releases were mints of this handler for deposits that
had locked nothing on Ethereum.

Roles, read on chain (`raw/E10/bsc_state.json`): the bridge's `resourceIDToHandlerAddress` returns one handler for
all three resource IDs in use (xETH, and a test token xTST under two IDs). For deposits with option 100 or 105 the
handler mints xETH to a delegate contract, which supplies it to the operator's xETH lending market, and the market
issues its shares to the recipient; for option 0 the handler mints to the recipient. Under option 105 the
operator's BNB lending market also lends the recipient 0.05 BNB in the same transaction (see Exclusions).

## How releases were captured

- Release record: the bridge's `ProposalEvent` with status 3 (executed). The event has two versions. Until the proxy
  upgrade of 2021-12-15T01:40:45Z it is `ProposalEvent(uint8 originDomainID, uint64 depositNonce, uint8 status,
  bytes32 dataHash)` with dataHash = keccak256(handler ++ data) (445 events: 156 active, 156 passed, 133 executed);
  afterwards `ProposalEvent(uint8, uint64, uint8, bytes data)` (172 events: 59, 59, 54). 52
  `FailedHandlerExecution` events mark proposals whose handler call failed; they stay at status 2.
- Proposal data (option, amount, recipient) and resource ID: read from the executing call into the bridge
  (`voteProposal` or `executeProposal`) in the call trace of each of the 187 executing transactions, and checked
  against the event: data equal (later version) or hash equal (earlier version). All 187 matched.
- One row per legitimate executed proposal: the xETH mint in the same transaction, whose amount equals the amount in
  the data and whose final recipient is the recipient in the data (kind `erc20`). Final recipient checked in all 64
  rows: 4 minted to the recipient (option 0), 60 minted to the delegate contract, supplied to the market, market
  shares minted to the recipient.
- Backing: each executed proposal is matched to the Ethereum bridge's `Deposit` with destination BSC and the same
  nonce. 61 rows have equal resource ID and data. In 3 rows (2021-12-21, 1 wei each) the deposit was made through a
  contract whose recipient differed from the depositing contract; the executed data names the depositing contract,
  with option and amount equal, and the mint went there.
- What each deposit locked, from the call trace of every deposit transaction (88) and its receipt: the ETH the
  Ethereum bridge forwarded to its handler (53 rows from direct `depositETH` calls, 3 from deposits made through
  contracts), or WETH transferred from the depositor to the Ethereum handler (8 rows, nonces 1 to 13; the last WETH
  deposit was made on 2021-12-09, the first native ETH deposit on 2021-12-14). The deposit fee was 0 in all 56 ETH
  deposits behind the rows.
- Per-row check for the pricing: in all 64 rows the xETH minted equals, to the wei, the ETH (or WETH) locked by the
  matched deposit.
- Deposit to release: median 3.2 minutes, maximum 13.7 hours.
- Timestamps: block time of the executing transaction.

## Reconciliation and completeness

- No block gaps: the bridge's logs and all xETH mints were read for every block from the deployment to the window
  end (93 chunks of 20,000 blocks), and the handler scans cover the same blocks.
- xETH mints: 73 over the bridge's life, all inside executed proposals and each matched to one: 64 legitimate
  releases, 2 releases to the failure's recipient, 7 zero-amount proposals.
- xETH supply: the token had no code before the deployment block and a supply of 198.277039 xETH at block
  14,742,021. The 73 mints (264.81004 xETH) minus 81 burns (66.533001 xETH, equal to the 81 BSC-side deposits of
  xETH bridged back to Ethereum) account for it exactly (residual 0).
- Handler and delegate contract (topic scans over the bridge's life): no token Transfer from the handler and none
  minted to it; the delegate contract received 69 xETH mints and passed each on in the same transaction (60
  legitimate, 2 to the failure's recipient, 7 of zero amount); it held no xETH at either end. Mints of the two tokens
  the handler can mint: 73 xETH and 114 xTST, all inside executed proposals.
- Native BNB: the handler, the delegate contract and the bridge held 0 BNB at both ends. No call by the bridge, the
  handler or the delegate contract carried BNB in any executed proposal. The only value-bearing calls are the 23
  loans of 0.05 BNB noted under Exclusions.
- Ethereum side: 86 deposits to BSC (nonces 1 to 86). 73 were executed in the window (the 64 rows, 7 zero-amount, 2
  to the failure's recipient). Of the other 13, 9 reached status 2 on BSC with a failed handler call (nonces 5, 8,
  12, 25, 26, 29 to 32; 0.255 ETH and WETH in all), nonces 9 and 10 (0.1 WETH each) were never proposed on BSC,
  nonce 28 locked nothing and was never proposed, and nonce 86 (190 ETH, locked nothing) is the failure's, executed
  in the failure block.

## Exclusions

- 114 executed proposals of the test token xTST (2021-11-24 to 2021-12-01, nonces 7 to 133 of the origin domain,
  10 xTST each to 13 recipients, 1,140 xTST in all). No deposit of the Ethereum bridge carries the xTST resource ID
  (the Ethereum bridge has no handler for it), so these mints are not backed releases. xTST has no price series.
  112 of them predate the first deposit on the Ethereum bridge (2021-11-29T11:29:58Z); the last two came on
  2021-12-01.
- 7 zero-amount proposals (2021-12-14 and 2021-12-17), matched to zero-amount deposits: nothing moved.
- 2 releases to the failure's recipient on the failure day, 0.1 ETH each at 21:22:00 and 21:26:42 UTC (234 USD
  each), backed by that address's own `depositETH` calls made 2.3 and 2.8 minutes earlier. They are part of the
  failure's preparation and left out; including them adds 0.2 ETH (468 USD).
- Not releases: 23 loans of 0.05 BNB (1.15 BNB) paid by the operator's BNB lending market to recipients in option-105
  executions (21 of the rows and the 2 releases above). The paying contract emitted `Borrow(borrower, amount,
  accountBorrows)` for the recipient and amount in the same transaction; the BNB did not come from the bridge, the
  handler or the delegate contract.
- Kept: the three 1-wei releases above (backed by 1 wei each); their USD value shows as 0.00.
- Movements between the bridge's own contracts are not rows: the delegate contract's onward transfer to the lending
  market is part of the same release.

## Totals

| asset | releases | amount (xETH = ETH) | USD at the time |
|---|---:|---:|---:|
| xETH (valued at ETH) | 64 | 264.61004 | 967,287 |

- Priced: 64 of 64 rows and 100% of the value, all from the DefiLlama `/chart` hourly ETH series within 2 h. xETH
  itself has no DefiLlama series (no hourly or daily point under its BSC contract key; checked). ETH ranged from
  3,137 to 4,770 USD per release.
- Releases: 13 under the earlier event version (2021-11-29 to 2021-12-14), 51 under the later one (2021-12-15 to
  2022-01-10); 39 with option 100, 21 with option 105, 4 with option 0; 19 distinct recipients.
- Release size: median 0.05 ETH (192 USD), 90th percentile 0.1 ETH (467 USD). Two releases hold 96% of the value:
  190 ETH (723,048 USD) and 64.6 ETH (204,843 USD). Without them: 62 releases, 10.01 ETH, 39,395 USD.
- Daily totals over the 150 days: mean 6,449 USD, median 0, 99th percentile 114,591, maximum 726,122. Over the 65.6
  days since the deployment: mean 14,749 USD, median 0, 90th percentile 472.
- Largest single release: 190 ETH (723,048 USD) at 2021-12-20T10:35:37Z. Next: 64.6 ETH (204,843 USD) at
  2022-01-10T06:49:36Z and 6 ETH (24,338 USD) at 2021-12-22T07:15:16Z.
- Busiest hour by USD: 2021-12-20 10:00 UTC, 723,048 USD (the 190 ETH release alone). By count: 2021-12-15 05:00
  UTC, 4 releases (578 USD).
- Busiest day by USD: 2021-12-20, 726,122 USD in 13 releases. By count: 2021-12-15, 15 releases (3,724 USD).
- Largest value released in any interval of length 10 min / 1 h / 6 h / 24 h: 723,048 / 723,048 / 725,346 /
  726,122 USD.
- Recipients: the largest took 74.8% of the USD (the 190 ETH release), the second 21.2%.

## Gaps

- Releases fall on 16 of the 66 calendar days from the deployment to the failure. Pauses longer than two days
  (from the deployment): 6.2 days to the first release (2021-11-29), 5.0, 5.2, 2.8, 7.8 (2021-12-22 to 12-30) and
  10.9 days (2021-12-30 to 2022-01-09), and 17.6 days from the last release (2022-01-10T06:49:36Z) to the window
  end. These are quiet periods of the bridge, not collection gaps: in each of the first six, the only Ethereum
  deposit to BSC is the one released at its end, made minutes before, and the BSC bridge emitted no proposal event
  during the 2.8-, 7.8- and 10.9-day pauses (the first pause holds the 112 earliest xTST executions). In the last
  pause the only deposits are the failure recipient's three (nonces 84 to 86) and the only executions are the two
  releases to it.
- No unpriced rows.

## Corrections to the method (2026-10-16)

The first version of `build_e10.py` (collection steps only) got two facts wrong on chain; both are fixed in the
script and its docstring.

- Handler. `handler_bsc` in `raw/E10/targets.json` (the contract that receives the minted xETH in a failure
  transaction) is the delegate contract, not the handler: the bridge's `resourceIDToHandlerAddress` returns another
  contract for every resource ID. The handler is now read on chain (`raw/E10/bsc_state.json`), and the completeness
  scans and balances cover the handler as well as the delegate contract (new step `scan`).
- Event versions. The docstring named only `ProposalEvent(uint8, uint64, uint8, bytes data)`. Before the proxy
  upgrade of 2021-12-15 the bridge emitted `ProposalEvent(uint8, uint64, uint8, bytes32 dataHash)`, which carries 133
  of the 187 executions, including 13 of the 64 releases. The build reads the data from the executing call in the
  transaction's call trace and checks it against the hash. The old `traces` step (later version only) is replaced by
  step `txs` (transaction, receipt and call trace of every execution of either version).
- Also changed: what a deposit locked is read from the call trace of every deposit transaction (ETH the Ethereum
  bridge forwarded to its handler) instead of the transaction value, which covers deposits made through contracts;
  value-bearing calls in executions are split into calls by the bridge, handler or delegate contract and loans by a
  lending market; the failure-block check reads all bridge logs of that block (both versions); balance reads return
  0 where xETH had no code yet; the `build` step is new.

## Fit for a limit

Complete for the release point: every executed proposal in the bridge's 65.6 days before the failure is matched to
its executing call, every xETH mint is accounted for and reconciled to the token supply, and every legitimate mint
equals the ETH or WETH locked by its deposit. The series is thin: 64 releases on 16 days, and two releases carry 96%
of the value. The last legitimate release came 17.6 days before the failure, so a fit window of the last 17 days
holds none. A limit fitted to it is well defined but rests on very few observations. Against it, the failure's 80M
USD is about 110 times the largest legitimate day (726,122 USD).
