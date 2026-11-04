# E15: legitimate releases before the failure (Nomad token bridge, Ethereum escrow)

File: `E15.csv` (columns ts_utc, leg, asset, amount, usd, kind, priced). Built 2026-10-16.

## Window and contracts

- Failure time T = first unauthorized release, 2022-08-01T21:32:31Z (`results/incidents.csv`).
- Window: 2022-03-04T21:32:31Z to 2022-08-01T21:32:30Z (150 days ending one second before T).
- Chain: Ethereum, blocks 14,322,947 to 15,259,100.
- Release point: the BridgeRouter (the token bridge's escrow on Ethereum), the single custody contract
  listed for this failure in `data/incidents/onchain_targets.json`. The failure drew only from this
  contract (operator postmortem), so this one leg is the whole release side.

## Method

- Raw logs: every ERC-20 Transfer log whose sender is the BridgeRouter, and every log the BridgeRouter
  emitted, over the block range (public archive RPC, `incidents/rpc.py`). Cached in `raw/E15/`.
- Release record: the BridgeRouter's own release event,
  `Receive(uint64 originAndNonce, address token, address recipient, address liquidityProvider, uint256 amount)`.
  An escrow Transfer counts as a release when the same transaction carries a Receive event for the same
  token and amount (the recipient is not matched, because a fast-liquidity provider can be the payee).
  One row per matched Transfer, kind `erc20`.
- Native asset: none. The BridgeRouter holds no ETH; Ether crosses as WETH and is released as a WETH
  transfer, which appears as asset `WETH`.
- Prices: DefiLlama `coins.llama.fi/chart` hourly series per token, nearest point within 2 hours; fallback
  daily series within 36 hours; otherwise unpriced. 14,499 rows priced hourly, 34 daily, 30 unpriced.
- Scripts: `fetch_logs_e14_e15.py E15 E15_eth 14322947 15259100` (raw logs), `process_e15.py E15` (CSV), summary numbers from
  `summarize_legit.py E15`.

## Exclusions

- Movements to the bridge's own addresses (the BridgeRouter and the Ethereum message receivers): none
  found in the window.
- Everything belonging to the failure: the window ends before the first unauthorized release, so no
  failure transaction is inside it.
- 660 Receive events with no escrow Transfer: these deliver bridge-issued representation tokens
  (wrapped assets of other chains, 8 token contracts), which are minted rather than released from escrow.
  They are not escrow releases and are left out.
- 2 escrow Transfers with no Receive event (one each of two minor tokens, both unpriced): not releases
  through the bridge's release path; left out.

## Totals

| Item | Value |
|---|---|
| Releases | 14,563 |
| Priced releases | 14,533 (99.8% by count) |
| USD released (priced rows) | 173.06M |
| Mean per day over 150 days | 1.15M |
| Median / 90th / 99th percentile release | 444 / 10.0k / 199.6k USD |
| Largest single release | 9.49M USD (USDC), 2022-07-25T05:50:24Z |
| Busiest hour by USD | 2022-07-25 05:00 UTC, 19.87M |
| Busiest hour by count | 2022-04-30 15:00 UTC, 157 releases |
| Busiest day by USD | 2022-07-25, 22.72M |
| Busiest day by count | 2022-04-30, 734 releases |
| Days with at least one release | 151 of 151 calendar dates touched |

By asset (USD): USDC 83.49M (8,180 releases), WETH 30.08M (5,226), FRAX 20.00M (41), USDT 17.82M (650),
WBTC 13.30M (219), DAI 7.59M (120), FXS 0.67M (18), other tokens under 0.1M combined.

## Gaps

- 30 releases of one minor token (asset `C3`) have no DefiLlama price and stay unpriced; their value is
  small relative to the total but unknown.
- No interval longer than two days without a release.
- Representation-token mints on Ethereum (see Exclusions) are a separate release path of the same
  bridge; they are not in this series. A limit on the escrow alone is fitted to the series as it stands.

## Fit for a limit

Complete for the escrow leg: every release event in the window is accounted for, 99.8% of releases are
priced, and the failure drew only from this contract.
