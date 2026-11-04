# Buying Time: research artifact

Data, code, prototype and testbed of the paper **Buying Time: What Withdrawal Limits Can Save on
Cross-Chain Bridges** (anonymous submission).

The repository contains the failure dataset with a source for every field, the release histories of the
failed bridges, the CCIP, Wormhole and stake datasets, the code that collected them, the scripts that
generate every number, table and figure of the paper, the exact checks of the paper's statements, two
limiter contracts with their tests and gas snapshots, and the two-chain testbed. It supports three levels
of reproduction:

| Level | What it does | Command | Time on the packaging machine |
|---|---|---|---|
| 1 | regenerates every number (`numbers.tex`), table (`tab_*.tex`) and data figure of the paper from the shipped result files | `python reproduce.py` | under a minute |
| 2 | reruns every analysis behind those result files from the shipped derived datasets, then level 1 | `python reproduce.py level2` | about 10 min |
| 3 | rebuilds the derived datasets from public chains, APIs and repositories with the shipped collection code | per dataset, [docs/collection.md](docs/collection.md) | hours to days; network access |

The prototype tests, the exact checks and the testbed are described below. The layout mirrors the
authors' workspace (`research_ideas/bridge_limits_paper/tex/` for the paper,
`research_ideas/probes/bridge_limits/` for data and code), so every script runs from its own location
without path changes. Paths below are relative to `research_ideas/probes/bridge_limits/` unless they
start with `research_ideas/` or name a file at the repository root.

## Requirements

- Python 3.11 (tested with 3.11.5) and the packages in `requirements.txt`; levels 1 and 2 need no network.
- Prototype and testbed: Foundry 1.8.5 (`forge`, `anvil`), which downloads solc 0.8.30, and forge-std
  v1.17.0 (installed by the command in [Prototype](#prototype)).
- Manuscript: a TeX distribution with IEEEtran (`pdflatex`, `bibtex`).
- Disk: the repository holds 393 files, 51 MB; `python reproduce.py unpack` adds about
  122 MB of plain CSV files (ignored by git).

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate      Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python reproduce.py            # level 1
python reproduce.py level2     # level 2 (unpacks the gzipped datasets first)
python reproduce.py checks     # unit test and exact checks
```

Every step writes its console output to `outputs/<step>.log` and prints its run time. The shipped outputs
are the files these commands wrote when the artifact was assembled, so after a run `git status` lists the
outputs whose content changed. Expected differences: the figure PDFs if the Times New Roman font is
missing (matplotlib then uses STIX; the numbers do not change), the time stamps `built_utc` in
`data/ccip/derived/flows_results.json` and `generated_utc` in `data/wormhole/flows/summary.json`, and
line endings, which git normalizes.

## Level 1: numbers, tables and figures

`python reproduce.py` runs three scripts in `research_ideas/bridge_limits_paper/tex/`:

- `make_numbers.py` writes `numbers.tex` (one LaTeX macro per number in the text) and `numbers.json`, and
  the intermediate files `timing.json`, `replay.json`, `robust.json`, `review.json` and `rolling.json`. Its
  asserts pin values that the text states in words. [docs/numbers.md](docs/numbers.md) lists every macro
  with its value, the sections that use it, the part of `make_numbers.py` that computes it, the files that
  part reads, and the script that writes each file.
- `make_tables.py` writes the ten `tab_*.tex` files.
- `make_figures.py` writes `figures/fig_example.pdf`, `fig_replay.pdf`, `fig_ccip.pdf` and
  `fig_perbridge.pdf` with the shared style in `hz_figstyle.py`. `figures/fig_pipeline.pdf` is the TikZ
  diagram `figures/fig_pipeline.tex` (`pdflatex fig_pipeline.tex`).

To compile the paper after level 1: `cd research_ideas/bridge_limits_paper/tex && pdflatex paper && bibtex
paper && pdflatex paper && pdflatex paper`.

Generated but not in the paper: `tab_response.tex` (response-time variants), `figures/fig_ccip.pdf`
(each studied CCIP lane's inbound bucket against its own traffic) and `figures/fig_perbridge.pdf` (the
trade-off curves of the limits fitted to each failed bridge's traffic). Other material the paper only
summarizes: `results/replay_perbridge.json` and `.md` (the limits fitted to each failed bridge's traffic for
margins 1 to 3, design response times of 1 to 50 hours and 60- and 120-day fit windows),
`results/delay_budget.md` (the per-bridge delay lower bounds), `results/replay_matched.json` (the
robustness variants of the traffic-matched replay), `results/incidents.csv` and `incidents.md` (all
69 records, not only the 20 largest failures of Table 9), and `results/testbed.json`
and `testbed.md` (every testbed configuration).

## Paper map

Section, table and figure numbers are those of the submitted version. "Data" lists the files that
`make_numbers.py`, `make_tables.py` or `make_figures.py` read; "Analysis" the level-2 scripts that write
them (level 3 builds their inputs, [docs/collection.md](docs/collection.md)).

| Paper | Data | Analysis |
|---|---|---|
| Abstract, Section 1, Fig. 1 (`fig_example.pdf`) | `results/incidents.csv`, `tex/replay.json`, `tex/rules.csv`, `tex/validation.csv`, `results/validation_bounds.json`, `results/replay_perbridge.json`, `results/delay_budget.json`, `results/coverage.json` | `incidents/05_build_dataset.py`, `replay_incidents.py`, `validation_bounds.py`, `replay_perbridge.py`, `delay_budget.py`, `coverage/counts.py` |
| Section 2.1, Fig. 2 | `tex/figures/fig_pipeline.tex` (TikZ, no data) | none |
| Section 2.2, Table 1 (`tab_rules.tex`), the CCIP census | `tex/rules.csv` (compiled by hand from `results/limiter_code_facts.md` Section 3, `results/deploy_controls.md`, `results/rules_controls.csv`), `data/ccip/derived/limits_distribution.json`, `data/ccip/derived/inbound_mismatch.json` | `ccip/limits_distribution.py`, `ccip/inbound_mismatch.py` |
| Section 2.3, Table 2 (`tab_timing.tex`) | `results/incidents.csv`, `results/incident_coding.csv` (coded by hand, rules in `results/incident_coding.md`), `results/blind_agreement.json` | `incidents/05_build_dataset.py`, `coding/agreement.py` |
| Section 4, Fig. 3 (`fig_replay.pdf`) | `results/incidents.csv`, `results/incident_coding.csv`, `results/replay_variants.json`, `results/blind_agreement.json`, `tex/replay.json` | `replay_incidents.py`, `replay_variants.py` |
| Section 5, Table 3 (in `paper.tex`) | `tex/rules.csv`, `results/replay_variants.json` | the table's formulas are checked by `first_layer_f6_20261015.py`, `first_layer_f7_20261016.py`, `first_layer_f9_20261016.py` |
| Section 6, Table 4 (`tab_validation.tex`) | `tex/validation.csv` (compiled by hand; `make_numbers.py` asserts its quantities against `results/validation_bounds.json`) | `validation_bounds.py` |
| Section 7, Table 10 (`tab_robust.tex`) | `results/replay_matched.json`, `results/replay_variants.json`, `tex/robust.json` | `replay_matched.py`, `replay_variants.py` |
| Section 7.1, Table 5 (`tab_perbridge.tex`) | `results/replay_perbridge.json`, `results/delay_budget.json`, `results/coverage.json`, `results/review_latency_ronin.json`, `data/ccip/derived/review_policy.json`, `rolling_v2.json`, `lags.json` | `replay_perbridge.py` (on the 20 histories in `data/legit/`), `delay_budget.py` |
| Section 7.2, Table 6 (`tab_ccip.tex`) | `ccip/selection.json`, `data/ccip/derived/review_policy.json`, `rolling_v2.json`, `rolling_policy.json`, `out_of_sample.json`, `recommended_buckets.json`, `inbound_mismatch.json`, `lags.json`, `results/review_latency_ronin.json` | `ccip/flows_analyze.py`, then `ccip/review_policy.py`, `rolling_v2.py`, `rolling_policy.py`, `out_of_sample.py`, `recommend_buckets.py`, `inbound_mismatch.py`, `lags.py` |
| Section 7.3 | `data/wormhole/derived/pooling_clean.json`, `data/wormhole/flows/summary.json`, `data/wormhole/flows/usage.csv`, `results/incidents.csv` | `wormhole/analyze_series.py`, `wormhole/pooling_clean.py` |
| Section 8, Table 7 (`tab_pbcost.tex`) | `results/replay_perbridge.json`, `results/response_protocol.json`, `results/replay_variants.json`, `results/delay_budget.json`, `results/coverage.json`, `data/ccip/derived/lags.json`, `tex/review.json` | `replay_perbridge.py`, `response_protocol.py`, `delay_budget.py` |
| Section 9, Table 8 (`tab_stake.tex`) | `tex/stake.csv` (compiled by hand from `results/stake_vs_value.md`), `data/stake/api/axelar_reads_*.json`, `data/stake/onchain/valuation_*.json`, `results/replay_matched.json` | `replay_matched.py`; the stake reads are level 3 (`stake/*.py`) |
| Section 10 | `tex/replay.json`, `results/replay_variants.json`, `tex/rules.csv`, `results/coverage.json`, `results/delay_budget.json` | as above |
| Section 11 | `prototype/snapshots/GasBench.json`, `TunedGasBench.json`, `test_summary.txt`, `test_suites.txt`, `gas_price.json`, `prototype/foundry.toml`, `results/testbed.json`, `results/testbed_forged.json` | `forge test` in `prototype/`; `prototype/testbed/summarize.py`, `summarize_forged.py` |
| Section 13 | `results/incidents.csv`, `results/blind_agreement.json` | as above |
| Appendix A | proofs in the text | exact checks `first_layer_*.py` (below) |
| Appendix B, Table 9 (`tab_failures.tex`) | `results/incidents.csv`, `results/incident_coding.csv`, `incidents/curation.py`, `results/coverage.json`, `results/blind_agreement.json`, `results/replay_matched.json` | `incidents/05_build_dataset.py`, `coverage/counts.py`, `coding/agreement.py` |
| Appendix C | `ccip/selection.json`, `data/ccip/derived/*.json`, `data/stake/*`, `results/review_latency_ronin.json` | as above |
| Section 8, the shadow run ("Is a short gate realistic?") | `results/shadow_run.json`, `results/shadow_fee_tokens.json`, `results/shadow_live.json` | `shadow/simulate.py` (on `shadow/data/*_releases.csv`); `shadow/fee_token_check.py` and `shadow/live_monitor.py` are level 3 |

## Level 2: the analyses

`python reproduce.py level2` unpacks the gzipped datasets and runs the steps below in this order, then
level 1. The listed times were measured when the artifact was assembled.

| Step | Script | Writes | Time |
|---|---|---|---|
| incidents_universe | `incidents/01_universe.py` | data/incidents/universe.json | not measured |
| incidents_dataset | `incidents/05_build_dataset.py` | results/incidents.csv, incidents.md | not measured |
| coding_redact | `coding/redact_labels.py` | coding/blind_input.csv (in place) | not measured |
| coding_agreement | `coding/agreement.py` | results/blind_agreement.json | not measured |
| coverage | `coverage/counts.py` | results/coverage.json | not measured |
| response_protocol | `response_protocol.py` | results/response_protocol.json | not measured |
| validation_bounds | `validation_bounds.py` | results/validation_bounds.json | not measured |
| histories_check | `data/legit/check_histories.py` | nothing (prints checks of the 20 histories) | not measured |
| replay_incidents | `replay_incidents.py` | results/incident_replay.md | not measured |
| wormhole_series | `wormhole/analyze_series.py` | data/wormhole/flows/* | not measured |
| wormhole_pooling | `wormhole/pooling_clean.py` | data/wormhole/derived/pooling_clean.json, results/wormhole_pooling_clean.md | not measured |
| ccip_flows | `ccip/flows_analyze.py` | data/ccip/derived/flows_results.json | not measured |
| ccip_recommend | `ccip/recommend_buckets.py` | data/ccip/derived/recommended_buckets.json, results/ccip_recommended_buckets.md | not measured |
| ccip_out_of_sample | `ccip/out_of_sample.py` | data/ccip/derived/out_of_sample.json, results/ccip_out_of_sample.md | not measured |
| ccip_rolling | `ccip/rolling_policy.py` | data/ccip/derived/rolling_policy.json, results/ccip_rolling_policy.md | not measured |
| ccip_rolling_v2 | `ccip/rolling_v2.py` | data/ccip/derived/rolling_v2.json, results/ccip_rolling_v2.md | not measured |
| ccip_review | `ccip/review_policy.py` | data/ccip/derived/review_policy.json, results/ccip_review_policy.md | not measured |
| ccip_inbound | `ccip/inbound_mismatch.py` | data/ccip/derived/inbound_mismatch.json | not measured |
| ccip_lags | `ccip/lags.py` | data/ccip/derived/lags.json | not measured |
| ccip_census | `ccip/limits_distribution.py` | data/ccip/derived/limits_distribution.json | not measured |
| replay_matched | `replay_matched.py` | results/replay_matched.json, .md | not measured |
| replay_variants | `replay_variants.py` | results/replay_variants.json, .md | not measured |
| replay_perbridge | `replay_perbridge.py` | results/replay_perbridge.json, .md | not measured |
| delay_budget | `delay_budget.py` | results/delay_budget.json, .md | not measured |
| testbed_summary | `prototype/testbed/summarize.py` | results/testbed.json, testbed.md | not measured |
| testbed_forged | `prototype/testbed/summarize_forged.py` | results/testbed_forged.json | not measured |
| shadow_simulate | `shadow/simulate.py` | results/shadow_run.json, shadow_run.md | not measured |
| make_numbers | `research_ideas/bridge_limits_paper/tex/make_numbers.py` | see Level 1 | not measured |
| make_tables | `research_ideas/bridge_limits_paper/tex/make_tables.py` | see Level 1 | not measured |
| make_figures | `research_ideas/bridge_limits_paper/tex/make_figures.py` | see Level 1 | not measured |

The analyses read only shipped files; the gzipped inputs are:

| File | Gzipped | Unpacked |
|---|---|---|
| `data/legit/E01.csv` | 0.1 MB | 0.8 MB |
| `data/legit/E05.csv` | 1.6 MB | 8.7 MB |
| `data/legit/E10.csv` | 1 kB | 5 kB |
| `data/legit/E11.csv` | 0.1 MB | 0.7 MB |
| `data/legit/E13.csv` | 1.0 MB | 5.0 MB |
| `data/legit/E14.csv` | 0.2 MB | 1.3 MB |
| `data/legit/E15.csv` | 0.2 MB | 1.1 MB |
| `data/legit/E16.csv` | 5.8 MB | 40.6 MB |
| `data/legit/E21.csv` | 99 kB | 0.5 MB |
| `data/legit/E22.csv` | 0.1 MB | 0.5 MB |
| `data/legit/E24.csv` | 6 kB | 32 kB |
| `data/legit/E25.csv` | 62 kB | 0.3 MB |
| `data/legit/E30.csv` | 0.2 MB | 1.0 MB |
| `data/legit/E45.csv` | 9 kB | 53 kB |
| `data/legit/E49.csv` | 6 kB | 40 kB |
| `data/legit/E50.csv` | 2 kB | 10 kB |
| `data/legit/E58.csv` | 3 kB | 17 kB |
| `data/legit/E59.csv` | 28 kB | 0.2 MB |
| `data/legit/E60.csv` | 6 kB | 31 kB |
| `data/legit/E64.csv` | 30 kB | 0.2 MB |
| `data/wormhole/tops_portal_hourly.csv` | 5.1 MB | 18.0 MB |
| `data/wormhole/tops_cctp_v2_hourly.csv` | 0.8 MB | 3.1 MB |
| `data/wormhole/hour_valuation.csv` | 0.5 MB | 1.8 MB |
| `data/wormhole/adjustments_small.csv` | 0.3 MB | 2.3 MB |
| `data/wormhole/transfers_classified.csv` | 3.2 MB | 20.1 MB |
| `shadow/live/polls.csv` | 2.9 MB | 15.6 MB |

## Exact checks and unit test

`python reproduce.py checks` runs `test_analysis_core.py` (the window envelope, bucket fitting and FIFO
replay of `analysis_core.py` against brute force; 10,979 cases) and the exact checks `first_layer_*.py`.
Each check enumerates small integer instances of a statement of the paper with exact integer or rational
arithmetic, prints a JSON line with the number of cases and failures, and exits with status 1 on a failure.
They use only the Python standard library and read and write no files. The docstring of each script lists
the statements and domains it covers (`first_layer_20261015.py`: control law, response functions of the
deployed rules, pooling, split requests, the concave hull; `f6` to `f11`: rule families, net flow and
regeneration, value weighting, rules in tandem, route cuts and timelocked control, the floor for
release-only defenses). Their run times were not measured when the artifact was assembled.

## Prototype

`prototype/` is a Foundry project: `src/OutflowLimiter.sol` (a hold, then release against one
value-weighted token bucket), `src/TunedLimiter.sol` (buckets in series, per-asset buckets, tightening at
once and loosening after a delay the pauser can cancel), `src/Baselines.sol`, and 48 tests in `test/`
(unit, fuzz with a fixed seed, an invariant test of the bound, and the gas harnesses that write
`snapshots/GasBench.json` and `snapshots/TunedGasBench.json`). Settings in `foundry.toml`: solc 0.8.30,
EVM Prague, optimizer 200 runs, `isolate = true`.

```sh
cd research_ideas/probes/bridge_limits/prototype
git clone --branch v1.17.0 --depth 1 https://github.com/foundry-rs/forge-std lib/forge-std   # commit f3dae6e
forge test                      # 48 tests; rewrites snapshots/GasBench.json and TunedGasBench.json
bash script/anvil_gas_check.sh  # optional: the same gas measured from receipts on a local anvil node
```

The snapshots are those of the authors' run. `snapshots/test_summary.txt` and `test_suites.txt` are the console output of the authors'
run. `prototype/gas_price.py` (level 3) reads the median base and priority fees over the 30 days before
block 26,201,369 from an Ethereum RPC endpoint and writes `snapshots/gas_price.json`.

## Testbed

`prototype/testbed/` replays a failed bridge's legitimate releases on two local anvil chains (source and
destination), with the prototype limiters at the release point, a relayer, a keeper, the monitor that
matches every release request to a source deposit, and injected unbacked requests. It needs Foundry,
`websockets`, `numpy` and `pycryptodome`, and the unpacked histories `data/legit/E25.csv` and
`data/legit/E15.csv` (`python reproduce.py unpack`).

```sh
cd research_ideas/probes/bridge_limits/prototype/testbed
forge build                                  # compiles the prototype sources into out/
python smoke.py                              # deploy, deposit, relay, execute, pause, cancel, roll back
python run_a.py E25_d2_k64 --ports 18701 18702   # one phase-A run (simulated time) -> logs/E25_d2_k64.json
python run_b.py 2 --reps 3 --ports 18901 18902   # phase B on the wall clock -> logs/rt_E25_d2.json
python run_forged.py --fid E25 --Bd 12 --k 64    # forged deposits -> logs/forged_E25_d12_k64.json
python summarize.py && python summarize_forged.py    # -> results/testbed.json, testbed.md, testbed_forged.json
```

The phase-A runs of the paper are `E25_d2_k64`, `E25_d12_k64`, `E25_d2_k12`, `E25_d2_k2`, `E25_d2_k2_reorg_a`,
`E25_d2_k2_reorg_b`, `E15_d2_k64` and `E15_d12_k64` (`run_rest_a.sh` runs six of them two at a time); phase B
is `run_b.py 2` and `run_b.py 12` (`run_b_all.sh`). On the authors' machine a phase-A run took 11 to 30
minutes, phase B 13 and 25 minutes, and the forged-deposit run 13 minutes. The shipped logs are the runs
behind the paper; `python reproduce.py level2` summarizes them again.

## Shadow run

`shadow/` runs the deposit-backing check of the paper over the recorded releases of two live bridges, every one of which is legitimate as far as anyone knows, so every alarm is a false alarm. The collectors (`ccip_collect.py`, `ccip_decode.py`, `wormhole_collect.py`, `wormhole_decode.py`) rebuild the release records from public chains and APIs (level 3); `simulate.py` replays the check on them (level 2, step `shadow_simulate`). `live_monitor.py` runs the same check on the two bridges as releases happen, polling public endpoints (`run_live.ps1` and `stop_live.ps1` start and stop it on Windows); it writes its records to `shadow/live/`.

Shipped data: `shadow/data/ccip_README.md`, `shadow/data/ccip_ethereum-bsc_releases.csv`, `shadow/data/wormhole_README.md`, `shadow/data/wormhole_ethereum_bsc_releases.csv`, `shadow/live/clock.csv`, `shadow/live/events.jsonl`, `shadow/live/finality.csv`, `shadow/live/polls.csv`, `shadow/live/status.json`, `shadow/live/sweeps.csv`, `shadow/live/twins.jsonl`, `results/shadow_fee_tokens.json`, `results/shadow_live.json`, `results/shadow_live.md`, `results/shadow_run.json`, `results/shadow_run.md`. In the CCIP records the token symbols are the pseudonyms of `data/ccip/`; the chain pair is named, because `simulate.py` takes the source chain's finality time from it.


## Level 3: rebuilding the datasets

[docs/collection.md](docs/collection.md) lists, per dataset, the collection scripts, their order, the
public endpoints and repositories they read, and what the artifact withholds. Level 3 rebuilds the
datasets by the same method; it does not reproduce the snapshot values exactly, because current prices,
live configurations and API pages change over time. Levels 1 and 2 reproduce the paper's numbers.

## Data and anonymization

[docs/data.md](docs/data.md) describes every dataset and the hand-compiled inputs. In short:

- No file contains a transaction hash or an address of a party behind a failure. The failure dataset
  (`results/incidents.csv`, 69 records, 57 of them failures of the bridge set) cites its sources per field
  and points to explorer block pages; the research notes it cites (`data/incidents/research/`) keep the
  quotes and URLs with addresses and hashes redacted. Contract addresses of bridges and protocols appear
  only in the level-3 collection targets and collector code.
- The paper reports no CCIP lane by name, and neither does the artifact: in the CCIP data (`ccip/`,
  `data/ccip/`) lanes, chains, tokens and price series appear as `lane-NN`, `chain-NNN`, `token-NNN` and
  `price-NN`, the same in every file. The shadow run's CCIP records use the same token pseudonyms and name their chain pair, as the paper does. The pseudonyms are labels, not protection: the
  studied lanes follow from the selection rule in `ccip/selection.json` applied to the public CCIP crawl
  (level 3).
- Raw caches, logs, cloned third-party code and downloaded literature are not included; third-party
  repositories are cited by URL and commit in [docs/collection.md](docs/collection.md).

## Licenses

Code: MIT (`LICENSE`). Derived data: CC BY 4.0 (`DATA_LICENSE`). Third-party data that the files quote,
such as the DefiLlama incident list, remain under their own terms.
## Public package

Repository: https://github.com/submissionrepo/buying-time-artifact

The linked manuscript PDF is included alongside its source. The release contains a ZIP of this repository.
The `forge-std` source and licenses used by the tests are included in the prototype's `lib/forge-std` directory.
