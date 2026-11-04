# E14: legitimate releases before the failure (Horizon bridge managers, Ethereum and BSC)

File: `E14.csv` (columns ts_utc, leg, asset, amount, usd, kind, priced). Built 2026-10-16.

## Window and contracts

- Failure time T = first unauthorized release, 2022-06-23T11:06:46Z (`results/incidents.csv`). The same T
  closes the window on both chains; the failure's single located BSC release came two hours later.
- Window: 2022-01-24T11:06:46Z to 2022-06-23T11:06:45Z (150 days ending one second before T).
- Ethereum blocks 14,067,979 to 15,012,645; BSC blocks 14,643,287 to 18,937,748 (both checked against
  block timestamps at the window edges).
- Release points (column `leg`). All are released by the same bridge multisig.

| leg | chain | role |
|---|---|---|
| ERC20 manager (escrow) | Ethereum | custody contract in `onchain_targets.json`; drawn in the failure |
| ETH manager (escrow) | Ethereum | custody contract in `onchain_targets.json`; drawn in the failure |
| BUSD manager (escrow) | Ethereum | third manager drawn in the failure (research batch_H) |
| BSC token manager (escrow) | BSC | contract at the same address as the BUSD manager; on BSC it escrows BUSD, BNB and other BEP-20 tokens; drawn in the failure |
| LINK manager (escrow; not in the failure's targets) | Ethereum | single-token escrow found among the multisig's executions; not drawn in the failure. Filter it out by `leg` if the limit should cover only the contracts that failed |

## Method

- Raw logs (public archive RPC, `incidents/rpc.py`; NodeReal for BSC): ERC-20 Transfer logs with each
  manager as sender, every log each manager emitted, and the bridge multisig's logs. Cached in `raw/E14/`.
- Release record: every manager emits `Unlocked(address token, uint256 amount, address recipient,
  bytes32 receiptId)` when the multisig executes an unlock. An escrow Transfer counts as a release when the
  same transaction carries an Unlocked event for the same token and amount (kind `erc20`).
- Fee-on-transfer tokens (PAXG, ROT and a few BSC tokens; 33 releases): the Transfer logs carry the net
  amount plus a fee transfer, the event the gross amount. These are matched within the transaction and the
  row carries the gross amount that left escrow.
- Native outflows: ETH (Ethereum ETH manager) and BNB (BSC token manager) leave only through the unlock
  function, which emits Unlocked with the native placeholder as token. Native releases are taken from
  these events (kind `event`: 2,613 ETH releases, 5,822 BNB releases). No trace scan was needed.
- Completeness check against the multisig: on Ethereum the multisig executed 6,692 transactions in the
  window: 5,886 unlocks by the three failed managers, 28 LINK manager unlocks, 774 mints of
  bridge-issued tokens, 3 NFT calls and 1 owner change. On BSC it executed 28,954: 11,016 unlocks and
  17,937 mints, all at the BSC token manager (mint destinations confirmed on a random sample of 300).
  Every unlock path is therefore in the series.
- Prices: DefiLlama `coins.llama.fi/chart` hourly series, nearest point within 2 hours; fallback daily
  within 36 hours; otherwise unpriced. DefiLlama keeps no historical series under the BSC contract keys
  of Binance-Peg tokens (BUSD, USDC, USDT, ETH, DAI, MATIC, ETC, BTCB), so these 4,152 releases are
  priced from the underlying asset's series, only where the on-chain symbol matches. 12,091 releases
  priced hourly, 20 daily, 4,152 through the peg, 655 unpriced.
- Scripts: `fetch_logs_e14_e15.py` and `fetch_e14_extra.py` (Ethereum logs), `fetch_e14_bsc.py` (BSC logs),
  `fetch_e14_multisig.py` (multisig execution destinations), `fetch_e14_other.py` (LINK manager),
  `build_e14.py` (CSV), `summarize_legit.py E14` (numbers below).

## Exclusions

- Movements to the bridge's own addresses (managers, multisig): none found in the window.
- The failure: the window ends before the first unauthorized release; no failure transaction is inside.
- Mints of bridge-issued tokens (774 on Ethereum, 17,937 on BSC): issued rather than released from escrow.
- NFT unlocks (3 multisig calls on Ethereum): non-fungible, not valued.
- 5 escrow Transfers with no Unlocked event (CNV, CLND, L3T, TSP on Ethereum; one minor BSC token):
  not through the release path; left out. 12 zero-amount and 3 to-zero-address transfers dropped.
- 12 Unlocked events with no Transfer (1 Ethereum, 11 BSC): zero-amount unlocks or tokens whose transfer
  emitted no standard log; left out.

## Totals

| Item | All legs | Ethereum legs | BSC leg |
|---|---|---|---|
| Releases | 16,918 | 5,913 | 11,005 |
| Priced releases | 16,263 (96.1%) | 5,880 (99.4%) | 10,383 (94.3%) |
| USD released (priced) | 762.09M | 725.53M | 36.55M |
| Largest single release | 58.12M | 58.12M (19,970 ETH, 2022-04-28T13:10:28Z) | 2.57M |
| Busiest hour by USD | 2022-04-28 13:00 UTC, 58.16M | 2022-04-28 13:00 UTC, 58.12M | 2022-04-01 03:00 UTC, 2.67M |
| Busiest day by USD | 2022-04-28, 80.83M | 2022-04-28, 80.59M | 2022-04-01, 3.80M |

By leg (USD): ERC20 manager 496.43M (2,911 releases), ETH manager 185.59M (2,613), BUSD manager 43.32M
(361), BSC token manager 36.55M (11,005), LINK manager 0.19M (28).
All legs: mean 5.08M per day; median release 759 USD, 90th percentile 62.6k, 99th percentile 739k.
Busiest hour by count 2022-01-25 21:00 UTC (43 releases); busiest day by count 2022-01-25 (367).
Releases on every calendar date of the window; no interval longer than two days without one.

## Gaps and cautions

- 655 releases unpriced, almost all on BSC (COBRA 352, WISB 40, 32 MATIC releases whose contract is not
  the Binance-Peg MATIC, bridge-issued tokens of other chains, tokens with no readable symbol, shown as
  `?`). Their USD value is unknown.
- Concentration: one recipient (an externally owned account, not one of the bridge's known addresses)
  received 86.8M in 4 releases, including the largest single release (58.1M of ETH) and a 21.0M release.
  Nothing on chain marks it as the operator's own address, so it stays in the series; a fit that is
  sensitive to the top tail should be checked with and without these releases. Label check (2026-10-16):
  Etherscan shows no public tag for this recipient; it was funded from an exchange-tagged wallet and
  transacted with addresses tagged as a trading firm and a liquidity protocol, so it reads as a large
  holder, not the operator.
- Binance-Peg pricing assumes the peg held at par with the underlying asset during the window.
- Releases by the multisig through mint paths are not escrow releases and are absent by design.

## Fit for a limit

Complete for the release points: every multisig unlock in the window on both chains is accounted for,
99.4% of Ethereum releases and 94.3% of BSC releases are priced. The Ethereum series is fit-ready; the
BSC series is usable with its unpriced tail stated.
