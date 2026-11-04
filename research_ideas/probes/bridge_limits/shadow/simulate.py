"""Shadow run of the deposit-backing check on recorded releases of two live bridges (2026-10-16).

Input: shadow/data/<bridge>_<pair>_releases.csv, one row per release over the 42 days [2026-09-04, 2026-10-16)
UTC, built by shadow/wormhole_collect.py and shadow/ccip_collect.py (columns: pair, release_ts_utc,
release_block, token, amount, usd, kind, matched, src_ts_utc, src_block, deposit_age_s, value_moved,
value_detail, amount_agrees, note). Every release in these files is legitimate as far as anyone knows, so every
alarm the check raises on them is a false alarm.

The check (paper Section 8) polls the destination chain every P seconds. A release included at time t_r is
first seen at the first poll after it, in (t_r, t_r + P]; it is confirmed at the first poll at which its source
message exists, moved its value, agrees in amount, token and recipient, and is ready: under "any included
deposit" a deposit is ready once included, under "final deposit" once its block is final. A release still
unconfirmed g seconds after it was seen raises an alarm; re-checks 60 and 300 seconds after the alarm clear it
if the release has been confirmed by then, and an alarm still standing after the second re-check is
confirmed. A release whose source does not match (no message, value not moved, or a disagreement) raises a
confirmed alarm.

Finality of the source block. Ethereum: a block in slot s of epoch E = s // 32 is final once the checkpoint of
epoch E + 1 is (the start of epoch E + 3), or, if it is the checkpoint of epoch E itself (s mod 32 = 0), at the
start of epoch E + 2: 12.8 to 19 minutes after the block. The live run's polls (live_monitor.py) saw the
finalized tag 64 to 95 blocks below the head, as this rule predicts. BSC: fast finality (BEP-126) makes a block
final once its child is justified, about two blocks (0.9 s at 0.45 s per block); the live polls saw the
finalized tag within two blocks of the head.

Configurations: deposit ready when included or when final; g in {0, 60 s}; P = 12 s; the poll's phase is
averaged over 12 equally spaced values. Outputs results/shadow_run.json and results/shadow_run.md: per bridge and
direction, releases and value, the releases the check cannot match (with the dataset's notes), how many
deposits were final when their release was included, false alarms raw and confirmed under each configuration
(expected counts over the poll phase), quantiles of the delay from inclusion to confirmation, and the releases
a 10-minute gate would hold beyond its 10 minutes.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import glob
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
P = 12.0
GRACES = (0.0, 60.0)
RECHECKS = (60.0, 300.0)
GATE_S = 600.0
PHASES = 12
GENESIS = 1606824023            # beacon chain genesis, 2020-12-01T12:00:23Z; slot s starts at GENESIS + 12 s
BSC_FINALITY_S = 2 * 0.45


def ts(s):
    return dt.datetime.strptime(s.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()


def final_time(chain, t):
    if chain == "ethereum":
        slot = int(round((t - GENESIS) / 12))
        e, k = divmod(slot, 32)
        return GENESIS + 12 * 32 * (e + (2 if k == 0 else 3))
    if chain == "bsc":
        return t + BSC_FINALITY_S
    raise ValueError(chain)


def quant(xs, q):
    if not xs:
        return math.nan
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def first_poll_at_or_after(t, phase):
    """Poll times are phase + k P."""
    return phase + math.ceil((t - phase) / P) * P


def simulate(rows, src_chain):
    out = {"releases": len(rows), "usd": sum(float(r["usd"] or 0) for r in rows),
           "unpriced": sum(1 for r in rows if not r["usd"])}
    bad = [r for r in rows if r["matched"] != "yes" or r["value_moved"] != "yes" or r["amount_agrees"] != "yes"]
    out["unmatched"] = len(bad)
    out["unmatched_usd"] = sum(float(r["usd"] or 0) for r in bad)
    out["unmatched_rows"] = [{k: r[k] for k in ("release_ts_utc", "token", "amount", "usd", "kind", "matched",
                                                 "value_moved", "amount_agrees", "note")} for r in bad]
    good = [r for r in rows if r not in bad]
    ages = [float(r["deposit_age_s"]) for r in good]
    out["deposit_age_s"] = {str(q): quant(ages, q) for q in (0.0, 0.01, 0.5, 0.99, 1.0)}
    fin = [final_time(src_chain, ts(r["src_ts_utc"])) - ts(r["release_ts_utc"]) for r in good]
    out["final_when_released"] = sum(1 for x in fin if x <= 0)
    out["not_final_when_released"] = sum(1 for x in fin if x > 0)
    out["finality_after_release_s_max"] = max(fin) if fin else math.nan
    out["configs"] = {}
    n = len(good) or 1
    for ready_name in ("any included deposit", "final deposit"):
        for g in GRACES:
            raw = confirmed = held = 0.0
            delays = []
            for r in good:
                rt, st = ts(r["release_ts_utc"]), ts(r["src_ts_utc"])
                ready = st if ready_name == "any included deposit" else final_time(src_chain, st)
                for j in range(PHASES):
                    phase = P * j / PHASES
                    seen = first_poll_at_or_after(rt + 1e-9, phase)
                    conf = seen if ready <= seen else first_poll_at_or_after(ready, phase)
                    delays.append(conf - rt)
                    if conf - rt > GATE_S:
                        held += 1.0 / PHASES
                    if conf - seen > g:
                        raw += 1.0 / PHASES
                        if conf - seen > g + RECHECKS[-1]:
                            confirmed += 1.0 / PHASES
            out["configs"][f"{ready_name}, grace {g:.0f} s"] = {
                "ready": ready_name, "grace_s": g, "false_alarms_raw": raw, "false_alarms_confirmed": confirmed,
                "raw_share": raw / n, "confirmed_share": confirmed / n, "held_by_gate": held,
                "delay_to_confirmation_s": {str(q): quant(delays, q) for q in (0.5, 0.99, 1.0)}}
    return out


def main():
    files = sorted(glob.glob(os.path.join(HERE, "data", "*_releases.csv")))
    res = {"poll_s": P, "graces_s": GRACES, "rechecks_s": RECHECKS, "gate_s": GATE_S,
           "bsc_finality_s": BSC_FINALITY_S, "bridges": {}}
    for f in files:
        bridge = os.path.basename(f).split("_")[0]
        with open(f, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        by_dir = collections.defaultdict(list)
        for r in rows:
            by_dir[r["pair"]].append(r)
        for pair, rs in sorted(by_dir.items()):
            res["bridges"][f"{bridge} {pair}"] = simulate(rs, pair.split("->")[0].strip())
    allb = list(res["bridges"].values())
    res["total"] = {"releases": sum(b["releases"] for b in allb), "usd": sum(b["usd"] for b in allb),
                    "unmatched": sum(b["unmatched"] for b in allb),
                    "not_final_when_released": sum(b["not_final_when_released"] for b in allb)}
    with open(os.path.join(ROOT, "results", "shadow_run.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    L = ["# Shadow run of the deposit-backing check on recorded releases (generated)", "",
         "Generated by `shadow/simulate.py`; see its docstring.", "",
         f"Total: {res['total']['releases']:,} releases, USD {res['total']['usd'] / 1e6:,.1f}M; "
         f"unmatched {res['total']['unmatched']}; deposits not final when released "
         f"{res['total']['not_final_when_released']}.", ""]
    for name, b in res["bridges"].items():
        L += [f"## {name}", "",
              f"Releases {b['releases']:,} (USD {b['usd'] / 1e6:,.1f}M, {b['unpriced']} unpriced); unmatched "
              f"{b['unmatched']} (USD {b['unmatched_usd']:,.0f}); deposits final when released "
              f"{b['final_when_released']:,}, not final {b['not_final_when_released']:,} (latest finality "
              f"{b['finality_after_release_s_max']:,.1f} s after the release).",
              "Deposit age at release (s): " + ", ".join(f"q{q}: {v:,.0f}" for q, v in b["deposit_age_s"].items()), ""]
        for u in b["unmatched_rows"]:
            L.append(f"- unmatched: {u['release_ts_utc']} {u['amount']} {u['token']} (USD {u['usd']}), {u['kind']}; "
                     f"matched {u['matched']}, value moved {u['value_moved']}, agrees {u['amount_agrees']}; {u['note']}")
        L += ["", "| configuration | false alarms raw | confirmed | held by a 10-min gate | delay to confirmation p50 / p99 / max (s) |",
              "|---|---|---|---|---|"]
        for cname, c in b["configs"].items():
            d = c["delay_to_confirmation_s"]
            L.append(f"| {cname} | {c['false_alarms_raw']:,.1f} ({100 * c['raw_share']:.2f}%) | "
                     f"{c['false_alarms_confirmed']:,.1f} ({100 * c['confirmed_share']:.2f}%) | {c['held_by_gate']:,.1f} | "
                     f"{d['0.5']:,.0f} / {d['0.99']:,.0f} / {d['1.0']:,.0f} |")
        L.append("")
    with open(os.path.join(ROOT, "results", "shadow_run.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
