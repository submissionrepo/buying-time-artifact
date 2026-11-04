# Level 3: rebuilding the datasets

The collection scripts read public blockchains (JSON-RPC, including archive state and traces), block
explorers, public APIs (DefiLlama, CoinGecko, CCIP API v2, Wormholescan, LayerZero Scan, Koios, mempool.space,
Axelar LCD) and public Git repositories. They need network access and run for hours; most cache every
response under a `raw/` directory next to their output (ignored by git; `python reproduce.py dirs` creates the
directories) and resume from the cache. Each script's docstring states its inputs, outputs and arguments.
Paths are relative to `research_ideas/probes/bridge_limits/`.

A rebuild follows the authors' method but does not reproduce the snapshot values exactly: current prices,
live configurations (the Wormhole Governor, the CCIP documentation), API pages and price revisions change. The
shipped derived datasets are the ones behind the paper, and levels 1 and 2 reproduce its numbers from them.

RPC endpoints are listed in `incidents/rpc.py`, `ethcall_lib.py` and the scripts that need other chains. For
BNB Smart Chain, set `BSC_RPC_URL` to an endpoint that serves historical logs and traces; the public BNB Chain
endpoints refuse `eth_getLogs`. The shadow run's live monitor also reads `NODEREAL_KEY` for NodeReal's BSC
endpoint; the access key the authors used is not included.

## Withheld identifiers

The artifact contains no address of a party behind a failure and no transaction hash. Where a collector
selected or excluded releases by such addresses, the targets that ship are reduced:

- `data/incidents/onchain_targets.json` (targets of `incidents/02_onchain_timing.py`): the recipient lists are
  replaced by `selected_releases`, the releases they received as `[block, symbol, amount]`, which the script
  matches instead. The two inflow targets `E23_inflow` and `E47_inflow` (`04_onchain_inflows.py`) consist of
  recipient addresses and cannot be rebuilt from the artifact; their selected rows ship in
  `data/incidents/onchain/`.
- `data/legit/targets/<ID>.json` (E01, E10, E21, E50, E58, E59): bridge and token contracts, blocks and
  endpoints. The failure recipients, the operators' signing and owner addresses (E01 router key, E50 vault
  owner) and the transaction hashes of the original targets are withheld. The collectors then keep the
  releases that went to the failure's recipients inside the window (for example, 43 for E21, 2 for E10 and 9
  for E58, which the shipped histories exclude), and `collect_legit_E01.py` no longer recognizes the router
  key's own transfers. Adding the addresses from the public post-mortems to the targets file restores the
  exclusions.
- `data/incidents/research/batch_*.json`: the on-chain references keep only the contracts that
  `data/legit/fetch_e14_extra.py`, `collect_legit_E45_E49_E60.py` and `collect_E64.py` read (release points,
  the LayerZero endpoint, the federation's peg address). The failure parties and transactions those scripts
  excluded (E45, E48 inside the E60 window, E49, E64) are withheld, with the same effect as above.
- CCIP: the shipped files use pseudonyms. A rebuild produces real names; `ccip/selection.json` must then be
  re-derived by applying its rule to `data/ccip/derived/lane_ranking.csv` (written by `flows_build.py rank`).

## Failure dataset

1. `incidents/01_universe.py`: the records considered, from the DefiLlama snapshot (refresh it from
   https://api.llama.fi/hacks to update) and the systematization's tables (in the script).
2. `incidents/02_onchain_timing.py [target ...]`: release rows from custody contracts (ERC-20 transfer logs and
   native-coin traces) over each target's block window, prices at the first release, pause events ->
   `data/incidents/onchain/<target>.json`, `onchain_summary.json`.
3. `incidents/03_onchain_bsc_tokenhub.py`: the two BNB releases of the BSC Token Hub (E16).
4. `incidents/04_onchain_inflows.py`: releases read as inflows to the recipients (E23, E47; withheld).
5. `incidents/05_build_dataset.py`: level 2.

The records themselves (`incidents/curation.py`) were compiled from the post-mortems, explorers and research
notes, with a source for every field; the notes are in `data/incidents/research/`.

## Release histories (`data/legit/`)

| History | Scripts, in order |
|---|---|
| E01 | `collect_legit_E01.py` |
| E05, E25 | `collect_legit_E05_E25.py` |
| E10 | `build_e10.py` |
| E11 | `collect_e11.py`, `collect_e11_traces.py`, `build_e11.py`, `reconcile_e11.py` |
| E13, E30 | `build_legit.py E13`, `build_legit.py E30`; `read_e30_limits.py <block before the upgrade>` for `E30_limits_state.json` |
| E14 | `fetch_e14_bsc.py`, `fetch_e14_extra.py`, `fetch_e14_multisig.py`, `fetch_e14_other.py`, `fetch_logs_e14_e15.py`, `build_e14.py` |
| E15 | `fetch_logs_e14_e15.py`, `process_e15.py` |
| E16 | `collect_e16.py`, `build_e16.py` |
| E21 | `collect_legit_E21.py` |
| E22, E24 | `collect_legit_E22_E24.py`, `stats_E22_E24.py` |
| E45, E49, E60 | `collect_legit_E45_E49_E60.py` (`recipients_E45_E49_E60.py`, `stats_E45_E49_E60.py`, `check_E45_lzscan.py` for the README checks) |
| E50 | `build_e50.py`, `check_e50.py` |
| E58 | `collect_legit_E58.py` |
| E59 | `build_e59.py` |
| E64 | `collect_E64.py fetch|build|price|write`, `stats_E64.py` |

Shared helpers: `pricing.py`, `pricing_points.py` (DefiLlama and CoinGecko prices), `summarize_legit.py` and
`show_summaries.py` (the README summaries), `../../incidents/rpc.py`. `check_histories.py` checks the result.

## Chainlink CCIP (`ccip/`)

1. `fetch_lanes_history.py`, `fetch_lanes_commits.py`: monthly snapshots of `lanes.json` and `tokens.json` from
   https://github.com/smartcontractkit/documentation (`src/config/data/ccip/v1_2_0/mainnet`) and the commit
   list; `data/ccip/lanes_history/manifest.json` records the commits used.
2. `lanes_table.py`: `lanes_current.csv`, `lanes_history.csv`, `prices_current.json` (DefiLlama current prices).
3. `fetch_messages.py`: the global crawl of the CCIP API v2 (https://api.ccip.chain.link) back to 2026-01-15.
4. `flows_build.py build` and `flows_build.py rank`: `transfers.csv.gz`, `lane_ranking.csv`,
   `ranking_meta.json` and the DefiLlama price series; then apply the rule of `selection.json`.
5. `fetch_lane_messages.py`: the per-lane crawls of the selected lanes (their full history).
6. `refine_param_dates.py`: dates of the bucket changes from the repository's commits.
7. `onchain_checks.py`: bucket settings from the pools' state and events by JSON-RPC
   (`data/ccip/onchain/amendments.json`).
8. Level 2: `flows_analyze.py` and the scripts after it.

## Wormhole (`wormhole/`)

1. `download_tops.py`: hourly volume by source chain from Wormholescan (Portal token bridge and CCTP v2).
2. `governor_history.py`, `governor_token_versions.py`, `governor_tokens.py`: the Governor's limits and token
   list over time from a clone of https://github.com/wormhole-foundation/wormhole (the authors used commit
   bb5957f321b0a9d168f52e906699ee77baa82a28; the docstring gives the clone and fetch commands);
   `governor_snapshot.py` reads the live Governor state.
3. `select_big_hours.py`, `select_windows.py`: the hours whose total could hold a transfer of at least the
   big-transaction size.
4. `download_vaas.py`, `collect_transfers.py`, `value_transfers.py` (with `--cg-extra extra_cg_ids.csv`),
   `api_values.py`, `verify_subhour.py`: decoded and valued transfers in those hours.
5. `build_adjustments.py --rules adjustment_rules.json --api-values <api_values.csv>`:
   `transfers_classified.csv`, `hour_valuation.csv`, `adjustments_full.csv`, `adjustments_small.csv`.
6. Level 2: `analyze_series.py --data <data/wormhole> --end 2026-10-15T16:00:00Z`, `pooling_clean.py`.

## Stake (`stake/`) and review latency (`data/review_latency/`)

- `stake_reads.py`, `polygon_validators.py`, `axelar_reads.py`, `value_calc.py`, in this order (with
  `../ethcall_lib.py`): reads at Ethereum block 26,201,369 and Axelar height 36,297,293, prices from DefiLlama
  and CoinGecko -> `data/stake/onchain/`, `data/stake/api/`. The shipped files are extracts of the fields the
  paper uses, under the names `make_numbers.py` reads.
- `data/review_latency/ronin_locks.py` (with `rl_common.py`): Ronin gateway lock and unlock events since 2022
  -> `raw/ronin/summary.json`; `ronin_public.py` -> `results/review_latency_ronin.json`.
- `prototype/gas_price.py`: median gas prices over the 30 days before block 26,201,369.

## Third-party sources

The facts in `results/limiter_code_facts.md` and `results/deploy_controls.md` were read from these
repositories at the commits given (not included):

| Repository | Commit |
|---|---|
| https://github.com/Consensys/linea-monorepo | 7952d16daaf5d0c0233859e7d65812c3a3299552 |
| https://github.com/DeFi-Circuit-Breaker/v1-core | 3960a0590ec3ee405b15273d9d4dc04f62fb5f9d |
| https://github.com/LayerZero-Labs/LayerZero-v2 | 9c741e7f9790639537b1710a203bcdfd73b0b9ac |
| https://github.com/LayerZero-Labs/devtools | 4973ba8bef7b0fdf7268469abea3ea50dbd4bbd8 |
| https://github.com/MystenLabs/sui (mainnet-v1.81.1) | e04cf9aa915cb6c069092733bebc3648755998e2 |
| https://github.com/axelarnetwork/axelar-amplifier | 6703b92bc4682b1320b06fda7c3168bbcb7bac5c |
| https://github.com/axelarnetwork/axelar-core | aaa8a4e1e4af2600d7c3614ae97416aeff5979ba |
| https://github.com/axelarnetwork/axelar-cgp-solidity | 43ec407499434448c91da71f031e618d3ed7578a |
| https://github.com/axelarnetwork/interchain-token-service | 0f4b03706c79ed9c364edd080aca4ae23a7e3642 |
| https://github.com/axieinfinity/ronin-bridge-contracts | b037428593c5d79808e7e34a808704a64d8b18a9 |
| https://github.com/axieinfinity/ronin-dpos-contracts | f301e1a624289f93a8312f348c83c7de7a2d222c |
| https://github.com/bnb-chain/bsc-genesis-contract | 84641812a013eda1593e058aeed4dc116c7746eb |
| https://github.com/celer-network/sgn-v2-contracts | dd60f9563d84127cd5cd33adcbe1df0fc14090e3 |
| https://github.com/circlefin/stablecoin-evm | fc85788bc7c23cefe3df1a757133048bfddadeaa |
| https://github.com/circlefin/evm-cctp-contracts | a92a2b4e7e6ef99bf0b05dca71780f5ec190e729 |
| https://github.com/defi-wonderland/xERC20 | da2afabdeb1bad9ccda2f6eb928cd99e852530be |
| https://github.com/gnosischain/tokenbridge-contracts | 47873407e00a147fec49d801f7159151d8fe9a33 |
| https://github.com/gnosischain/omnibridge | ccd9003d99eb0bda86e7f3320d08804f2f98cff8 |
| https://github.com/hyperlane-xyz/hyperlane-monorepo | e3eee02129b5fd302daf0f44c9816a9b0e7b80a1 |
| npm @layerzerolabs/console-oft-evm-contracts, oft-upgradeable-evm-contracts, utils-upgradeable-evm-contracts | version 1.2.83 |
| https://github.com/omni/tokenbridge-contracts | 908a48107919d4ab127f9af07d44d47eac91547e |
| https://github.com/smartcontractkit/chainlink-ccip | 055a7e78d705b8e1857b235cc3b6ab39f18ee1f8 and bccdd15b734ea6c0e6d1b3d36c482e64ced2d441 (v1.6.4) |
| https://github.com/starknet-io/starkgate-contracts | 07e11c39119a10d5742735be5b1d51894ebf5311 |
| https://github.com/taikoxyz/taiko-mono | 719449773217e277782b4d60e0b225e17b9a67f3 |
| https://gitlab.com/thorchain/thornode | 8eb2d08c6aa099005b33a322aa01278b9db32db7 |
| https://github.com/wormhole-foundation/wormhole | bb5957f321b0a9d168f52e906699ee77baa82a28 |
| https://github.com/wormhole-foundation/native-token-transfers | commit not recorded (source archive) |
| THORNode type definitions (archive) | commit not recorded (source archive) |
| https://github.com/foundry-rs/forge-std (prototype dependency) | v1.17.0, f3dae6e6ee381f25eb6a246f7da9b85c91a68219 |

## Shadow run

The scripts in `shadow/` collect the release records over their own period from public RPC endpoints, explorer APIs and DefiLlama; each docstring lists its steps. They keep their caches under `shadow/raw/` (not shipped). The BSC endpoints they use can be set with `BSC_RPC_URL`.
