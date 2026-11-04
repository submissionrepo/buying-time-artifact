# Shadow run of the deposit-backing check (paper Section 8)

The check of Section 8 confirms each release of a bridge against a deposit on the sending chain that moved the
value and agrees with the release in amount, token and recipient. This folder runs it in shadow on two live
bridges between Ethereum and BSC, Wormhole's token bridge and Chainlink CCIP, both directions: first on their
recorded releases of 42 days, then live.

## Recorded releases, 2026-09-04 to 2026-10-16 (UTC)

| file | built by | rows |
|---|---|---|
| `data/wormhole_ethereum_bsc_releases.csv` | `wormhole_collect.py` (steps targets, pairs, collect, traces, sources, crosscheck, coverage, build) | one per release |
| `data/ccip_ethereum-bsc_releases.csv` | `ccip_collect.py` (steps pair, targets, releases, sources, build, coverage, selftest) | one per release and token |

Columns: pair, release_ts_utc, release_block, token, amount, usd, kind, matched, src_ts_utc, src_block,
deposit_age_s, value_moved, value_detail, amount_agrees, note. Both tables carry no addresses and no transaction
hashes; the collectors keep those under `raw/` (not in the artifact). Each collector's README in `data/` states
the decoding rules, the coverage checks against the bridge's explorer API and a second RPC provider, and the
price sources.

- `simulate.py` replays a check that polls every 12 seconds on these releases, with deposits accepted once
  included or once final (Ethereum finality by slot, BSC fast finality), grace periods of 0 and 60 seconds and
  re-checks after 60 and 300 seconds. Output: `../results/shadow_run.json` and `.md`.
- `fee_token_check.py` reads the receipts of the releases the check did not match and tests a second rule (the
  transfers out of custody sum to the signed amount and one goes to the recipient). Output:
  `../results/shadow_fee_tokens.json`.

## Live run, from 2026-10-16 16:37 UTC

`live_monitor.py` polls both chains every 12 seconds through public endpoints, decodes each release with the
same code as the recorded tables, checks it at once, re-checks it 60 and 300 seconds later (then every 15
minutes for a day) if it was not confirmed, re-reads the blocks of the last hour at most through another endpoint 5 to 15 minutes
later to find releases the polls missed (after an outage the older blocks are read once only), and checks three forged copies of every release (one citing a source
message that was never issued, one with the amount raised by one unit, one paying another recipient). Its
docstring gives the details.

- `shadow/live/` holds what the run publishes, without addresses or hashes: `events.jsonl` (one line per release
  once its checks end), `twins.jsonl`, `polls.csv`, `finality.csv`, `sweeps.csv`, `clock.csv` and
  `status.json`.
- `live_monitor.py summary` writes `../results/shadow_live.json` and `.md` from these files.
- Start with `run_live.ps1`: a scheduled task of the current user runs the monitor under pythonw (no console
  window) at logon and every 10 minutes, skipping a run while the monitor is up, so it also restarts the monitor
  after a crash. Stop with `stop_live.ps1`, which writes `live/STOP` (the monitor exits within a minute and does
  not start while the file exists) and removes the task (`-KeepTask` keeps it). Run in a terminal with
  `python -I shadow/live_monitor.py run [--minutes N]` from `probes/bridge_limits`.

The monitor sends no transaction; it only reads public RPC endpoints.
