"""Traffic-matched replay, robustness of the replay, and the price of a single bucket (2026-10-16).

1. Matched replay.  The replay in replay_incidents.py uses the same limit for every bridge.
   Here every failure meets a release-point limit sized to legitimate traffic: the greedy
   shaper with curve E (Theorem floor, h = 0), where E is the envelope of the combined
   traffic of Wormhole's token bridge on nine chains, the largest legitimate traffic we
   measured.  Such a limit delays no legitimate transfer of that traffic.  Variants:
     small  E of the transfers below the Governor's size threshold (large transfers are
            held apart; the party splits its withdrawals, so it meets this curve);
     full   E of all transfers (no hold on large transfers).
   Periods: the last 12 and 24 months to 2026-10-15.  Loss of failure i with first response
   D_i (hours): min(A_i, E(ceil(D_i))) if its class is V, D or S, else A_i.  E is
   nondecreasing, so rounding D up to whole hours can only overstate the loss.
2. Robustness of the uniform replay and of the matched replay: response times doubled or
   delayed by 1 h and 6 h; only the failures whose first response was a pause; failures
   weighted equally instead of by value; the largest failure left out.
3. Price of a single bucket: least concave majorant over the envelope, E^(D) / E(D), for the
   nine-chain small-transfer series (hourly grid up to 30 days) and for the CCIP lanes
   (data/ccip/derived/recommended_buckets.json, transfer-level, computed there).
Outputs: results/replay_matched.json and results/replay_matched.md.
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "wormhole"))
import replay_incidents as ri  # noqa: E402
from analysis_core import hull_value, upper_concave_hull  # noqa: E402
from pooling_clean import END, PERIODS, dense, load  # noqa: E402

COVERED = {"V", "D", "S"}


def pooled(series, start):
    arr = None
    for chain, pts in series.items():
        a = dense(pts, start, END)
        arr = a if arr is None else arr + a
    return arr


def envelope_fn(arr):
    c = np.concatenate([[0.0], np.cumsum(arr)])
    cache = {}

    def E(k):
        k = max(1, int(k))
        if k not in cache:
            cache[k] = float((c[k:] - c[:-k]).max()) if len(arr) >= k else float(arr.sum())
        return cache[k]
    return E


def events():
    rows = ri.load(os.path.join(HERE, "results", "incidents.csv"))
    basis = {}
    with open(os.path.join(HERE, "results", "incidents.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            basis[r["id"]] = r.get("response_basis", "")
    timed = [e for e in rows if not math.isnan(e["D_h"])]
    for e in timed:
        e["basis"] = basis.get(e["id"], "")
    return timed


def contained(timed, loss_of, weight="value"):
    if weight == "value":
        tot = sum(e["A"] for e in timed)
        return 1 - sum(loss_of(e) for e in timed) / tot
    return statistics.mean(1 - loss_of(e) / e["A"] for e in timed)


def variants(timed, loss_with_D):
    """Containment under the robustness variants for a loss function loss_with_D(event, D)."""
    out = {}
    out["base"] = contained(timed, lambda e: loss_with_D(e, e["D_h"]))
    out["D_times_2"] = contained(timed, lambda e: loss_with_D(e, 2 * e["D_h"]))
    out["D_plus_1h"] = contained(timed, lambda e: loss_with_D(e, e["D_h"] + 1))
    out["D_plus_6h"] = contained(timed, lambda e: loss_with_D(e, e["D_h"] + 6))
    pauses = [e for e in timed if e["basis"] in ("pause", "pause report")]
    out["pauses_only"] = contained(pauses, lambda e: loss_with_D(e, e["D_h"]))
    out["n_pauses"] = len(pauses)
    out["event_weighted"] = contained(timed, lambda e: loss_with_D(e, e["D_h"]), weight="event")
    big = max(timed, key=lambda e: e["A"])
    rest = [e for e in timed if e is not big]
    out["without_largest"] = contained(rest, lambda e: loss_with_D(e, e["D_h"]))
    out["largest_share_of_value"] = big["A"] / sum(e["A"] for e in timed)
    # the three largest failures left out, and a bootstrap over failures
    # (value-weighted share, 2,000 resamples with a fixed seed, 5th and 95th percentiles)
    top3 = sorted(timed, key=lambda e: -e["A"])[:3]
    rest3 = [e for e in timed if all(e is not t for t in top3)]
    out["without_top3"] = contained(rest3, lambda e: loss_with_D(e, e["D_h"]))
    out["top3_share_of_value"] = sum(e["A"] for e in top3) / sum(e["A"] for e in timed)
    rng = np.random.default_rng(20261016)
    L = np.array([loss_with_D(e, e["D_h"]) for e in timed])
    Aa = np.array([e["A"] for e in timed])
    idx = rng.integers(0, len(timed), size=(2000, len(timed)))
    boot = 1 - L[idx].sum(axis=1) / Aa[idx].sum(axis=1)
    out["boot_lo"], out["boot_hi"] = (float(x) for x in np.quantile(boot, [0.05, 0.95]))
    return out


def main():
    timed = events()
    res = {"n_timed": len(timed), "value_timed": sum(e["A"] for e in timed), "matched": {}, "robust": {}}
    full, small = load("series_full_hourly.csv"), load("series_small_hourly.csv")
    envs = {}
    for period, start in PERIODS.items():
        for name, series in (("small", small), ("full", full)):
            envs[(name, period)] = envelope_fn(pooled(series, start))

    def matched_loss(E):
        def unseen(e):
            return e["cls"] not in COVERED or (e["cls"] == "D" and e.get("flaw_reach") == "yes")
        # one limit per release contract, each matched to the benchmark (Corollary 4.2)
        return lambda e, D: e["A"] if unseen(e) else min(e["A"], e.get("n_chains", 1) * E(math.ceil(D)))

    for (name, period), E in envs.items():
        key = f"{name}|{period}"
        res["matched"][key] = {
            "contained": contained(timed, lambda e: matched_loss(E)(e, e["D_h"])),
            "E_at": {f"{k}h": E(k) for k in (1, 4, 6, 24, 72, 168)},
        }
        res["robust"][f"matched {key}"] = variants(timed, matched_loss(E))

    # stake under the flow condition (Corollary stake): what the matched limit lets out per response,
    # over the empirical response times of the timed failures, for the benchmark traffic
    Ds = sorted(e["D_h"] for e in timed)
    flow = {}
    for key in ("full|12 months", "small|12 months"):
        name, period = key.split("|")
        E = envs[(name, period)]
        vals = [E(math.ceil(D)) for D in Ds]
        flow[key] = {"median_D_h": statistics.median(Ds), "E_at_median_D": E(math.ceil(statistics.median(Ds))),
                     "mean_over_D": statistics.mean(vals),
                     "mean_over_D_capped_7d": statistics.mean(E(min(math.ceil(D), 168)) for D in Ds),
                     "share_D_over_7d": sum(D > 168 for D in Ds) / len(Ds)}
    res["flow_condition"] = flow

    # robustness of the uniform replay (release point)
    for shape, param in (("ramp", 1e6), ("cliff", 24.0), ("freeze", 1e7)):
        def uni(e, D, shape=shape, param=param):
            return ri.loss({**e, "D_h": D}, shape, param, "release")
        res["robust"][f"uniform {shape} {param:g}"] = variants(timed, uni)
    # the verifier-side ceiling under the same variants
    res["robust"]["verifier ramp 1e+06"] = variants(timed, lambda e, D: ri.loss({**e, "D_h": D}, "ramp", 1e6, "verifier"))

    # price of a single bucket: nine-chain small transfers, last 12 months, hourly grid to 30 days
    E = envs[("small", "12 months")]
    pts = [(float(k), E(k)) for k in range(1, 24 * 30 + 1)]
    hull = upper_concave_hull(pts)
    res["single_bucket_wormhole"] = {f"{D}h": {"E": E(D), "hull": hull_value(hull, float(D)),
                                               "ratio": hull_value(hull, float(D)) / E(D)} for D in (3, 6, 12, 24, 72)}
    rec = json.load(open(os.path.join(HERE, "data", "ccip", "derived", "recommended_buckets.json"), encoding="utf-8"))
    for D in ("1 h", "6 h"):
        ratios = sorted(r[D]["hull_over_E"] for r in rec)
        res[f"single_bucket_ccip_{D.replace(' ', '')}"] = {
            "n": len(ratios), "median": statistics.median(ratios), "max": ratios[-1], "min": ratios[0],
            "share_above_1_1": sum(x > 1.1 for x in ratios) / len(ratios)}

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "replay_matched.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    nl = chr(10)
    lines = ["# Traffic-matched replay, robustness and the price of a single bucket (generated)", "",
             "Generated by `replay_matched.py`. Loss of a timed failure under a release-point limit sized to the combined legitimate "
             "traffic of Wormhole's token bridge on nine chains: min(A, E(ceil(D))) for classes V, D, S; the full amount otherwise.", "",
             "## Matched replay: share of the value contained", "", "| envelope | contained | E(1h) | E(6h) | E(24h) | E(7d) |", "|---|---|---|---|---|---|"]
    for key, v in res["matched"].items():
        e = v["E_at"]
        lines.append(f"| {key} | {v['contained']:.3f} | {e['1h']/1e6:.1f} | {e['6h']/1e6:.1f} | {e['24h']/1e6:.1f} | {e['168h']/1e6:.1f} |")
    lines += ["", "## Robustness (share of value contained unless noted)", "",
              "| rule | base | D x 2 | D + 1 h | D + 6 h | pauses only (n) | event-weighted | without largest |", "|---|---|---|---|---|---|---|---|"]
    for key, v in res["robust"].items():
        lines.append(f"| {key} | {v['base']:.3f} | {v['D_times_2']:.3f} | {v['D_plus_1h']:.3f} | {v['D_plus_6h']:.3f} | "
                     f"{v['pauses_only']:.3f} ({v['n_pauses']}) | {v['event_weighted']:.3f} | {v['without_largest']:.3f} |")
    lines += ["", "## Price of a single bucket: least concave majorant over the envelope", "",
              "Wormhole, nine chains, small transfers, last 12 months:", ""]
    for D, v in res["single_bucket_wormhole"].items():
        lines.append(f"- D = {D}: E = {v['E']/1e6:.2f}M, majorant = {v['hull']/1e6:.2f}M, ratio {v['ratio']:.3f}")
    for D in ("1h", "6h"):
        v = res[f"single_bucket_ccip_{D}"]
        lines.append(f"- CCIP lanes (n = {v['n']}), D = {D}: median ratio {v['median']:.3f}, range {v['min']:.3f} to {v['max']:.3f}, "
                     f"share above 1.1: {v['share_above_1_1']:.2f}")
    with open(os.path.join(HERE, "results", "replay_matched.md"), "w", encoding="utf-8") as fh:
        fh.write(nl.join(lines) + nl)
    print(json.dumps({k: v for k, v in res.items() if k != "robust"}, indent=1)[:4000])
    for key, v in res["robust"].items():
        print(key, {k: round(x, 3) if isinstance(x, float) else x for k, x in v.items()})


if __name__ == "__main__":
    main()
