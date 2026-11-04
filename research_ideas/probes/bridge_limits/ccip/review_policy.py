"""CCIP: a matched bucket for small transfers plus review of large ones (2026-10-16).

rolling_v2.py showed that a bucket refitted to 90 days of a lane's traffic delays a smaller
share of value than today's bucket but makes the transfers it delays wait far longer: the
long waits come from a few transfers larger than anything in the fit window, which today's
operators pass by raising limits by hand.  This script evaluates the design that the
paper recommends for such transfers: every 30 days, set a size threshold s at the q-quantile
of transfer sizes in the previous 90 days; transfers of size s or more wait for a review;
the rest pass a bucket fitted (min_r B(r) + r D, times a margin m) to the smaller transfers
of the previous 90 days.  The party behind a failure can split its withdrawals below s, so
its exposure within D is the small-transfer bucket's b + r D (the paper's Proposition on
holds by observable class).  Inbound buckets at the release point, execution times.
Reported against today's inbound bucket on the same segments: share of value delayed by the
bucket, wait quantiles, mean delay per dollar, reviews (count per lane-month and value
share), and the release within 1 h and 6 h relative to today's bucket.
Outputs: data/ccip/derived/review_policy.json, results/ccip_review_policy.md.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import analysis_core as ac  # noqa: E402
from rolling_v2 import DS, L, S, fifo_delays, quant, segments  # noqa: E402

QS = [None, 0.99, 0.995]
MS = [1.0, 1.5, 2.0]


def run(times, vals, D, m, q, cur, segs, price):
    acc = {"tot": 0.0, "dl_v": 0.0, "dl_n": 0, "waits": [], "vh": 0.0, "rev_v": 0.0, "rev_n": 0,
           "cur_dl_v": 0.0, "cur_vh": 0.0, "betas": {k: [] for k in DS}, "months": 0}
    for (a, z) in segs:
        fit = [(t, v) for t, v in zip(times, vals) if a - L <= t < a]
        test = [(t, v) for t, v in zip(times, vals) if a <= t < z]
        if not fit or not test:
            continue
        s = float(np.quantile([v for _, v in fit], q)) if q else math.inf
        small_fit = [(t, v) for t, v in fit if v < s]
        if not small_fit:
            continue
        ft, fv = zip(*small_fit)
        b, r, _ = ac.best_bucket_exact(list(ft), list(fv), D)
        b, r = m * b, m * r
        small = [(t, v) for t, v in test if v < s]
        large = [(t, v) for t, v in test if v >= s]
        acc["months"] += 1
        acc["tot"] += sum(v for _, v in test) * price
        acc["rev_v"] += sum(v for _, v in large) * price
        acc["rev_n"] += len(large)
        if small:
            tt, tv = zip(*small)
            d = fifo_delays(list(tt), list(tv), b * (1 + 1e-9) + 1e-6, r)
            for v, w in zip(tv, d):
                if w > 1e-9:
                    acc["dl_v"] += v * price
                    acc["dl_n"] += 1
                    acc["waits"].append(w / 3600.0)
                    acc["vh"] += v * price * min(w, 30 * 86400.0) / 3600.0
        tt, tv = zip(*test)
        cd = fifo_delays(list(tt), list(tv), cur["b"] * (1 + 1e-9) + 1e-6, cur["r"])
        for v, w in zip(tv, cd):
            if w > 1e-9:
                acc["cur_dl_v"] += v * price
                acc["cur_vh"] += v * price * min(w, 30 * 86400.0) / 3600.0
        for k, dd in DS.items():
            acc["betas"][k].append(b + r * dd)
    return acc


def main():
    fr = json.load(open(os.path.join(ROOT, "data", "ccip", "derived", "flows_results.json"), encoding="utf-8"))
    tr = pd.read_csv(os.path.join(ROOT, "data", "ccip", "derived", "transfers.csv.gz"),
                     usecols=["message_id", "src", "dst", "token", "amount", "receipt_ts"]).drop_duplicates("message_id")
    per = {}
    for lane in fr["results"]:
        cur = (lane.get("current_bucket") or {}).get("in") or {}
        if not cur.get("enabled"):
            continue
        sub = tr[(tr.src == lane["src"]) & (tr.dst == lane["dst"]) & (tr.token == lane["token"])].dropna(subset=["receipt_ts"]).sort_values("receipt_ts")
        if len(sub) < 50:
            continue
        times = sub.receipt_ts.astype(float).tolist()
        vals = sub.amount.astype(float).tolist()
        if times[-1] - times[0] < L + S:
            continue
        price = (lane.get("price") or {}).get("now_usd") or float("nan")
        segs = segments(times)
        name = (lane.get("lane") or f"{lane['token']} {lane['src']} -> {lane['dst']}")
        for Dk, D in DS.items():
            for m in MS:
                for q in QS:
                    key = f"{Dk} m={m} q={q}"
                    a = run(times, vals, D, m, q, cur, segs, price)
                    a["cur_beta"] = {k: cur["b"] + cur["r"] * dd for k, dd in DS.items()}
                    a["price"] = price
                    per.setdefault(key, {})[name] = a
    pooled = {}
    for key, lanes in per.items():
        tot = sum(a["tot"] for a in lanes.values())
        waits = [w for a in lanes.values() for w in a["waits"]]
        ratios = {k: sorted(statistics.mean(a["betas"][k]) / a["cur_beta"][k] for a in lanes.values() if a["betas"][k]) for k in DS}
        sums = {k: sum(statistics.mean(a["betas"][k]) * a["price"] for a in lanes.values() if a["betas"][k]) /
                sum(a["cur_beta"][k] * a["price"] for a in lanes.values() if a["betas"][k]) for k in DS}
        months = sum(a["months"] for a in lanes.values())
        pooled[key] = {
            "n_lanes": len(lanes), "lane_months": months,
            "delayed_share": sum(a["dl_v"] for a in lanes.values()) / tot,
            "delayed_n": sum(a["dl_n"] for a in lanes.values()),
            "wait_p50_h": quant(waits, 0.5), "wait_p90_h": quant(waits, 0.9),
            "mean_delay_h_per_dollar": sum(a["vh"] for a in lanes.values()) / tot,
            "review_share": sum(a["rev_v"] for a in lanes.values()) / tot,
            "reviews_per_lane_month": sum(a["rev_n"] for a in lanes.values()) / months if months else math.nan,
            "current_delayed_share": sum(a["cur_dl_v"] for a in lanes.values()) / tot,
            "current_mean_delay_h_per_dollar": sum(a["cur_vh"] for a in lanes.values()) / tot,
            "median_cap_ratio": {k: (v[len(v) // 2] if v else math.nan) for k, v in ratios.items()},
            "sum_cap_ratio": sums,
        }
    json.dump({"pooled": pooled}, open(os.path.join(ROOT, "data", "ccip", "derived", "review_policy.json"), "w", encoding="utf-8"), indent=1)
    nl = chr(10)
    lines = ["# CCIP: matched bucket for small transfers plus review of large ones (generated)", "",
             "Generated by `ccip/review_policy.py`. Inbound buckets, execution times, 30-day segments refitted on 90 days. q: size quantile of the review threshold in the fit window (None: no review).", "",
             "| policy | lanes | delayed share | delayed transfers | wait p50 (h) | wait p90 (h) | mean delay per dollar (h) | review value share | reviews per lane-month | today: delayed share | today: mean delay per dollar (h) | median cap ratio 1 h | 6 h | sum ratio 1 h | 6 h |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, p in pooled.items():
        lines.append(f"| {key} | {p['n_lanes']} | {p['delayed_share']:.3f} | {p['delayed_n']} | {p['wait_p50_h']:.2f} | {p['wait_p90_h']:.1f} | {p['mean_delay_h_per_dollar']:.3f} | "
                     f"{p['review_share']:.3f} | {p['reviews_per_lane_month']:.2f} | {p['current_delayed_share']:.3f} | {p['current_mean_delay_h_per_dollar']:.3f} | "
                     f"{p['median_cap_ratio']['1 h']:.2f} | {p['median_cap_ratio']['6 h']:.2f} | {p['sum_cap_ratio']['1 h']:.2f} | {p['sum_cap_ratio']['6 h']:.2f} |")
    open(os.path.join(ROOT, "results", "ccip_review_policy.md"), "w", encoding="utf-8").write(nl.join(lines) + nl)
    print(nl.join(lines))


if __name__ == "__main__":
    main()
