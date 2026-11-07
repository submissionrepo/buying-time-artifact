# Datasets

Paths are relative to `research_ideas/probes/bridge_limits/` unless they start with `research_ideas/`.
Every dataset below is an input of level 2 or level 1; the level-3 scripts that build it are listed in
[collection.md](collection.md).

## Failures

- `results/incidents.csv` and `results/incidents.md`: the failure dataset, 69 records, of which the
  57 with `in_bridge_set = yes` are the unauthorized releases from a bridge's escrow, minting or
  liquidity that the paper studies. One row per record with the value released, the class, the side that
  released, the times of the first and last unauthorized release, the time by which 90% of the value had left,
  the first public alert, the operator's first acknowledgment, the pause, the limits in force, the chains and
  assets, the value later returned or frozen, and for each of these a source column. Release times come from
  the chains where the releases could be traced; those rows cite the explorer pages of the first and last
  release block. `incidents.md` states the definitions and the summary statistics.
  Built by `incidents/05_build_dataset.py` from:
  - `incidents/curation.py`: one record per event with a source for every field (the curated data, kept in
    Python for its comments);
  - `data/incidents/universe.json`: the records considered (`incidents/01_universe.py` from the DefiLlama
    snapshot `data/incidents/defillama_hacks_20261015.json`, downloaded from api.llama.fi/hacks on 2026-10-15,
    plus the incidents of the 2024 systematization's Tables 5 and 8 that DefiLlama does not flag);
  - `data/incidents/onchain_summary.json` and `data/incidents/onchain/*.json`: release paths measured from
    chain data. The per-target files keep the selected release rows (time, block, chain, kind, symbol, amount,
    USD) and pause times, not transaction hashes, senders, recipients or token addresses;
  - `data/incidents/research/batch_*.json`: the research notes that `curation.py` and the dataset cite as
    "research batch_X". For every event and field they give the value and the sources with a verbatim quote.
    References to transaction and address pages are withheld and addresses and hashes in the text are
    redacted; the only addresses left are the bridge contracts that level-3 collectors read.
- `results/incident_coding.csv` and `.md`: the second coding pass by hand (class, detection channel, pause
  holder, recovered value, chains released, borderline tags, whether a flaw reached a limit, whether taken
  keys controlled the releasing contract); the coding rules are in the `.md` file.
- `coding/`: the blind coding. `codebook.md` is what the coder was given, `blind_input.csv` the input (the
  failure descriptions and public sources from the dataset, with earlier codes removed by
  `redact_labels.py`), `blind_coding.csv` the coder's output, `blind_coding_notes.md` the coder's notes, and
  `agreement.py` compares the codings (`results/blind_agreement.json`).
- `coverage/`: the entries of three published lists (Wu et al. 2025, Table 6; Zhang et al. 2024, Table 4;
  Lee et al. 2023, the examples), transcribed from the papers and matched to the dataset by hand;
  `coverage/counts.py` writes `results/coverage.json`.
- `results/validation_bounds.json`: the two predicted quantities of Section 7 (`validation_bounds.py`, from
  `incidents/curation.py` and `data/legit/E30_limits_state.json`, an extract of the Ronin gateway's limits
  read on chain at the block before the first release).

## Release histories of the failed bridges

`data/legit/<ID>.csv.gz`, one per failure with a rebuilt history (20 files; `python reproduce.py unpack`
writes the `.csv` files the scripts read). Each holds every release of the bridge's release contracts over the
150 days that end one second before the failure's first unauthorized release: `ts_utc`, `leg`, `asset`,
`amount`, `usd` (DefiLlama price of the hour, or of the day where no hourly price exists), `priced` and `kind`.
Transfers to the bridge's own addresses are dropped; the per-history `<ID>_README.md` files describe the
release point, the method, the exclusions and the checks. `replay_perbridge.py` and `delay_budget.py` read them;
`data/legit/check_histories.py` prints their coverage.

## Chainlink CCIP

The paper reports no lane by name, so lanes, chains, tokens and price series appear as pseudonyms
(`lane-NN`, `chain-NNN`, `token-NNN`, `price-NN`), the same in every file. The 18 studied lanes are
`lane-01` to `lane-18` in the order of `ccip/selection.json`, which also states the selection rule.

- `data/ccip/derived/lanes_current.csv`: every token lane configured in the CCIP documentation repository at
  its commit of 2026-10-14 (smartcontractkit/documentation, `lanes.json` and `tokens.json`), with both buckets
  that apply to a transfer (the source pool's outbound bucket and the destination pool's inbound bucket),
  decimals, pool versions and current USD values; column `lane` marks the studied lanes.
- `data/ccip/derived/lanes_history.csv`: the same fields for the studied lanes in monthly snapshots of the
  repository since August 2024; `param_changes_refined.json` dates each change within its bracket from the
  repository's commits; `data/ccip/onchain/amendments.json` holds bucket settings read from the pools' own
  state and events, which replace the documented values where they disagree.
- `data/ccip/derived/transfers.csv.gz`: the CCIP API v2 crawl. Every transfer keeps its source chain, status
  and send and execution times (`ccip/lags.py`); the transfers of the studied lanes also keep the crawl they
  came from (`origin`), the lane's chains and token, the amount, and a synthetic id in the order of the
  original message ids.
- `data/ccip/prices/price-NN_{1d,1h}.json`, `derived/prices_current.json`, `derived/ranking_meta.json`:
  DefiLlama price series and current prices of the studied tokens.
- `data/ccip/messages_all/state.json`, `messages_lane/lane-NN/state.json`, `lanes_history/manifest.json`: the
  state of the crawls (window, pages, message counts) and the documentation commits.
- Outputs of level 2 in `data/ccip/derived/` (`flows_results.json`, `recommended_buckets.json`,
  `out_of_sample.json`, `rolling_policy.json`, `rolling_v2.json`, `review_policy.json`,
  `inbound_mismatch.json`, `lags.json`, `limits_distribution.json`) and `results/ccip_*.md`.

## Wormhole

- `data/wormhole/tops_portal_hourly.csv.gz`, `tops_cctp_v2_hourly.csv.gz`: hourly USD volume by source chain
  of the Portal token bridge and of CCTP v2 (Wormholescan), from September 2021 to 2026-10-15 16:00 UTC.
- `data/wormhole/transfers_classified.csv.gz`: every decoded transfer in the hours that could hold a transfer
  of at least the Governor's big-transaction size, with the classification `analyze_series.py` uses (chain,
  hour, in the adjusted series, at or above the big-transaction size, at or above $1 million, token on the
  Governor list, value in USD).
- `data/wormhole/adjustments_full.csv`, `adjustments_small.csv.gz`: value removed from each chain-hour and the
  reason (the documented 2022-02-02 event, valuation outliers, unlisted tokens, big transfers);
  `hour_valuation.csv.gz`: the chain-hours with per-transfer data.
- `data/wormhole/governor/governor_settings.csv`: the Governor's daily limit and big-transaction size per chain
  over time, from the history of the Wormhole repository.
- Outputs of level 2: `data/wormhole/flows/` and `data/wormhole/derived/pooling_clean.json`.

## Stake, review latency, prototype

- `data/stake/api/axelar_reads_20261016T000617Z.json`, `data/stake/onchain/valuation_20261016T000856Z.json`:
  extracts of the stake reads (Axelar validator stake at height 36,297,293; Ethereum reads at block
  26,201,369; prices at 2026-10-16 00:08 UTC). `research_ideas/bridge_limits_paper/tex/stake.csv` (Table 8)
  is compiled by hand from `results/stake_vs_value.md`, which records each value with its read and source.
- `results/review_latency_ronin.json` and `.csv`: the withdrawals that Ronin's gateway locked for review since
  2022 and their unlock times.
- `prototype/snapshots/`: gas measured by the test harness and the console output of the authors' test run.
- `prototype/testbed/logs/`: the testbed runs behind the paper (local test chains; transaction hashes and
  accounts of those chains are replaced by `local-tx-N` and `local-account-N`).

## Tables compiled by hand

- `research_ideas/bridge_limits_paper/tex/rules.csv` (Table 1): the deployed rules, from
  `results/limiter_code_facts.md` Section 3 (behavior read from source code at pinned commits),
  `results/deploy_controls.md` and `results/rules_controls.csv` (who controls each limit).
- `research_ideas/bridge_limits_paper/tex/validation.csv` (Table 4): the failures that met a limit in force;
  `make_numbers.py` asserts its quantities against `results/validation_bounds.json`.
- `research_ideas/bridge_limits_paper/tex/stake.csv` (Table 8): see above.

## Shadow run

`shadow/data/ccip_README.md`, `shadow/data/ccip_ethereum-bsc_releases.csv`, `shadow/data/wormhole_README.md`, `shadow/data/wormhole_ethereum_bsc_releases.csv`, `shadow/live/clock.csv`, `shadow/live/events.jsonl`, `shadow/live/finality.csv`, `shadow/live/polls.csv`, `shadow/live/status.json`, `shadow/live/sweeps.csv`, `shadow/live/twins.jsonl`, `results/shadow_fee_tokens.json`, `results/shadow_live.json`, `results/shadow_live.md`, `results/shadow_run.json`, `results/shadow_run.md`: the release records of the shadow run (one row per release with its matched source deposit; no addresses or transaction hashes; CCIP token symbols as pseudonyms) and, where present, the simulation's summary. The scripts' docstrings describe the columns and the method.

## Not included

Raw RPC, explorer and API caches (`raw/` directories, about 2.5 GB), console logs, cloned third-party
repositories (cited in [collection.md](collection.md)), downloaded literature, saved documentation pages, the
CCIP reports that name lanes, earlier or superseded analyses, and the authors' internal notes. The level-3
collectors rebuild the caches.
