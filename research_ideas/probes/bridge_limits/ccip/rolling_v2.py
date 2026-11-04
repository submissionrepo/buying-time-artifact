"""CCIP, second pass: inbound buckets at the release point, historical configurations,
wait times, both response times, and a margin chosen out of sample (2026-10-16).

Changes from rolling_policy.py:
- The release point of a CCIP transfer is the destination token pool, whose inbound bucket
  acts at execution time.  Policies and the deployed bucket are replayed on execution
  (receipt) times against the inbound bucket; the outbound replay on send times is kept as
  a second reading.
- Baselines on the same 30-day segments: (a) today's bucket; (b) the configuration in force
  at the time (documentation history and on-chain readings, flows_results.json
  *_regimes).  Under (b) every observed transfer passed (flows_results *_inforce: no
  transfer rejected or queued), so we report how much of the value moved while the bucket
  was disabled.
- Delay: share of value delayed, number of transfers delayed, and wait-time quantiles of
  the delayed transfers (FIFO fluid replay, closed form as in analysis_core).
- Every policy is evaluated at D = 1 h and D = 6 h: its time-average release within each D
  divided by today's bucket's (median over lanes, and the ratio of sums over lanes).
- Margin chosen out of sample: per lane the segments are split in time; the margin is the
  smallest m in M whose pooled delayed share on the first halves is at most TARGET; it is
  then evaluated on the second halves.
Outputs: data/ccip/derived/rolling_v2.json, results/ccip_rolling_v2.md.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import analysis_core as ac  # noqa: E402

DAY = 86400.0
L, S = 90 * DAY, 30 * DAY
DS = {"1 h": 3600.0, "6 h": 21600.0}
MS = [1.0, 1.25, 1.5, 2.0, 3.0]
TARGET = 0.05
TARGETS = [0.05, 0.10]
POOLED_WAITS = {}


def fifo_delays(times, values, b, r):
    """Per-request delay (seconds) of a FIFO fluid token bucket, full at the start."""
    order = sorted(range(len(times)), key=lambda i: (times[i], i))
    A_before, m = 0.0, math.inf
    out = [0.0] * len(times)
    for i in order:
        t, v = times[i], values[i]
        m = min(m, A_before + b - r * t)
        y = A_before + v
        release = max(t, (y - m) / r) if r > 0 else (t if y <= m + 1e-12 else math.inf)
        out[i] = release - t
        A_before = y
    return out


def segments(times):
    t0, t_end = times[0], times[-1]
    s = t0 + L
    segs = []
    while s < t_end:
        segs.append((s, s + S))
        s += S
    return segs


def replay(times, vals, D, m, cur, segs):
    """Per segment: tested value, delays under the policy and under today's bucket, betas."""
    rows = []
    for (a, z) in segs:
        fit = [(t, v) for t, v in zip(times, vals) if a - L <= t < a]
        test = [(t, v) for t, v in zip(times, vals) if a <= t < z]
        if not fit or not test:
            continue
        ft, fv = zip(*fit)
        b, r, _ = ac.best_bucket_exact(list(ft), list(fv), D)
        b, r = m * b, m * r
        tt, tv = list(zip(*test))
        pol = fifo_delays(list(tt), list(tv), b * (1 + 1e-9) + 1e-6, r)
        curd = fifo_delays(list(tt), list(tv), cur["b"] * (1 + 1e-9) + 1e-6, cur["r"]) if cur else None
        rows.append({"a": a, "value": sum(tv), "vals": list(tv), "pol": pol, "cur": curd,
                     "beta": {k: b + r * d for k, d in DS.items()}})
    return rows


DOLLAR_HOURS = {}


def summarize(rows, price, which="pol", key=None):
    tot = sum(r["value"] for r in rows) * price
    dl_v, dl_n, waits, vh = 0.0, 0, [], 0.0
    for r in rows:
        d = r[which]
        if d is None:
            continue
        for v, w in zip(r["vals"], d):
            if w > 1e-9:
                dl_v += v * price
                dl_n += 1
                waits.append(w / 3600.0)
                vh += v * price * min(w, 30 * 86400.0) / 3600.0
    if key is not None:
        acc = DOLLAR_HOURS.setdefault(key, [0.0, 0.0])
        acc[0] += vh
        acc[1] += tot
    return tot, dl_v, dl_n, waits


def quant(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = min(len(xs) - 1, max(0, int(math.ceil(q * len(xs))) - 1))
    return xs[k]


def disabled_share(regimes, times, vals, segs):
    """Share of tested value that moved while the in-force bucket was disabled or unknown."""
    tot = dis = 0.0
    first = segs[0][0] if segs else math.inf
    for t, v in zip(times, vals):
        if t < first:
            continue
        tot += v
        state = None
        for g in regimes:
            if g["from_ts"] <= t < g["to_ts"]:
                state = g["state"]
                break
        if state != "enabled":
            dis += v
    return dis / tot if tot else math.nan


def main():
    fr = json.load(open(os.path.join(ROOT, "data", "ccip", "derived", "flows_results.json"), encoding="utf-8"))
    tr = pd.read_csv(os.path.join(ROOT, "data", "ccip", "derived", "transfers.csv.gz"),
                     usecols=["message_id", "src", "dst", "token", "amount", "send_ts", "receipt_ts"]).drop_duplicates("message_id")
    out = {"lanes": [], "params": {"L_days": 90, "S_days": 30, "margins": MS, "target": TARGET}}
    for lane in fr["results"]:
        sub = tr[(tr.src == lane["src"]) & (tr.dst == lane["dst"]) & (tr.token == lane["token"])]
        price = (lane.get("price") or {}).get("now_usd") or float("nan")
        rec = {"lane": (lane.get("lane") or f"{lane['token']} {lane['src']} -> {lane['dst']}"), "price_usd": price, "directions": {}}
        for direction, col in (("in", "receipt_ts"), ("out", "send_ts")):
            s = sub.dropna(subset=[col]).sort_values(col)
            if len(s) < 50:
                rec["directions"][direction] = {"skipped": f"{len(s)} transfers"}
                continue
            times = s[col].astype(float).tolist()
            vals = s.amount.astype(float).tolist()
            if times[-1] - times[0] < L + S:
                rec["directions"][direction] = {"skipped": "history shorter than 120 days"}
                continue
            cur = (lane.get("current_bucket") or {}).get(direction) or {}
            cur = cur if cur.get("enabled") else None
            segs = segments(times)
            half = len(segs) // 2
            dres = {"n_segments": len(segs), "has_bucket_now": cur is not None,
                    "disabled_share_inforce": disabled_share(lane.get(f"{direction}_regimes") or [], times, vals, segs),
                    "cur_beta": {k: (cur["b"] + cur["r"] * d) if cur else None for k, d in DS.items()},
                    "policies": {}}
            for Dk, D in DS.items():
                for m in MS:
                    rows = replay(times, vals, D, m, cur, segs)
                    pol_all = summarize(rows, price, "pol", key=(direction, f"{Dk} m={m}") if cur else None)
                    pol_first = summarize([r for r in rows if r["a"] < segs[half][0]] if half else rows, price, "pol")
                    pol_second = summarize([r for r in rows if r["a"] >= segs[half][0]] if half else [], price, "pol")
                    cur_all = summarize(rows, price, "cur", key=(direction, "cur") if (Dk, m) == ("1 h", 1.0) else None) if cur else None
                    betas = {k: statistics.mean(r["beta"][k] for r in rows) for k in DS} if rows else {}
                    POOLED_WAITS.setdefault((direction, f"{Dk} m={m}"), []).extend(pol_all[3])
                    if cur_all:
                        POOLED_WAITS.setdefault((direction, "cur"), [])
                        if (direction, Dk, m) == (direction, "1 h", 1.0):
                            POOLED_WAITS[(direction, "cur")].extend(cur_all[3])
                    dres["policies"][f"{Dk} m={m}"] = {
                        "all": pol_all[:3] + (quant(pol_all[3], 0.5), quant(pol_all[3], 0.95), max(pol_all[3]) if pol_all[3] else 0.0),
                        "first": pol_first[:3], "second": pol_second[:3],
                        "cur": (cur_all[:3] + (quant(cur_all[3], 0.5), quant(cur_all[3], 0.95), max(cur_all[3]) if cur_all[3] else 0.0)) if cur_all else None,
                        "mean_beta": betas}
            rec["directions"][direction] = dres
        out["lanes"].append(rec)

    # pooled results per direction and policy
    pooled = {}
    for direction in ("in", "out"):
        lanes = [l for l in out["lanes"] if "policies" in l["directions"].get(direction, {})]
        withb = [l for l in lanes if l["directions"][direction]["has_bucket_now"]]
        pooled[direction] = {"n_lanes": len(lanes), "n_with_bucket": len(withb), "policies": {}}
        for key in lanes[0]["directions"][direction]["policies"] if lanes else []:
            def agg(ls, part):
                tot = sum(l["directions"][direction]["policies"][key][part][0] for l in ls)
                dv = sum(l["directions"][direction]["policies"][key][part][1] for l in ls)
                dn = sum(l["directions"][direction]["policies"][key][part][2] for l in ls)
                return (dv / tot if tot else math.nan), dn
            share_all, n_all = agg(withb, "all")
            share_first, _ = agg(withb, "first")
            share_second, n_second = agg(withb, "second")
            cur_tot = sum(l["directions"][direction]["policies"][key]["cur"][0] for l in withb)
            cur_dv = sum(l["directions"][direction]["policies"][key]["cur"][1] for l in withb)
            cur_dn = sum(l["directions"][direction]["policies"][key]["cur"][2] for l in withb)
            ratios, sums_p, sums_c = {}, {}, {}
            for k in DS:
                rs = sorted(l["directions"][direction]["policies"][key]["mean_beta"][k] / l["directions"][direction]["cur_beta"][k]
                            for l in withb if l["directions"][direction]["cur_beta"][k])
                ratios[k] = rs[len(rs) // 2] if rs else math.nan
                sums_p[k] = sum(l["directions"][direction]["policies"][key]["mean_beta"][k] * l["price_usd"] for l in withb)
                sums_c[k] = sum(l["directions"][direction]["cur_beta"][k] * l["price_usd"] for l in withb)
            waits = [l["directions"][direction]["policies"][key]["all"][3:] for l in withb]
            pooled[direction]["policies"][key] = {
                "delayed_share": share_all, "delayed_n": n_all, "first_half": share_first, "second_half": share_second,
                "second_half_n": n_second,
                "current_delayed_share": cur_dv / cur_tot if cur_tot else math.nan, "current_delayed_n": cur_dn,
                "median_cap_ratio": ratios, "sum_cap_ratio": {k: sums_p[k] / sums_c[k] if sums_c[k] else math.nan for k in DS},
                "lane_wait_p50_h_median": statistics.median(w[0] for w in waits) if waits else math.nan,
                "lane_wait_p95_h_max": max(w[1] for w in waits) if waits else math.nan}
        # margin chosen on first halves, evaluated on second halves
        for Dk in DS:
            for target in TARGETS:
                chosen = None
                for m in MS:
                    p = pooled[direction]["policies"].get(f"{Dk} m={m}")
                    if p and p["first_half"] <= target:
                        chosen = m
                        break
                pooled[direction][f"chosen_m_{Dk}_{target:.2f}"] = chosen
            pooled[direction][f"chosen_m_{Dk}"] = pooled[direction][f"chosen_m_{Dk}_{TARGET:.2f}"]
        for key, p in pooled[direction]["policies"].items():
            w = POOLED_WAITS.get((direction, key), [])
            p["pooled_wait_p50_h"] = quant(w, 0.5)
            p["pooled_wait_p90_h"] = quant(w, 0.9)
        for key, p in pooled[direction]["policies"].items():
            acc = DOLLAR_HOURS.get((direction, key), [0.0, 0.0])
            p["mean_delay_h_per_dollar"] = acc[0] / acc[1] if acc[1] else float("nan")
        acc = DOLLAR_HOURS.get((direction, "cur"), [0.0, 0.0])
        pooled[direction]["current_mean_delay_h_per_dollar"] = acc[0] / acc[1] if acc[1] else float("nan")
        wc = POOLED_WAITS.get((direction, "cur"), [])
        pooled[direction]["current_wait_p50_h"] = quant(wc, 0.5)
        pooled[direction]["current_wait_p90_h"] = quant(wc, 0.9)
        dis = [l["directions"][direction]["disabled_share_inforce"] for l in withb]
        pooled[direction]["disabled_share_inforce_median"] = statistics.median(dis) if dis else math.nan
        pooled[direction]["n_lanes_disabled_over_half"] = sum(x > 0.5 for x in dis)
    out["pooled"] = pooled
    json.dump(out, open(os.path.join(ROOT, "data", "ccip", "derived", "rolling_v2.json"), "w", encoding="utf-8"), indent=1, default=str)

    nl = chr(10)
    lines = ["# CCIP: inbound buckets, historical configurations, wait times, margins chosen out of sample (generated)", "",
             "Generated by `ccip/rolling_v2.py`. See the docstring for definitions.", ""]
    for direction in ("in", "out"):
        P = pooled[direction]
        lines += [f"## {'Inbound (release point, execution times)' if direction == 'in' else 'Outbound (sending side, send times)'}", "",
                  f"Lanes replayed: {P['n_lanes']}; with a bucket today: {P['n_with_bucket']}. Median share of tested value that moved while the in-force bucket was disabled: {P['disabled_share_inforce_median']:.3f}; lanes where it exceeds one half: {P['n_lanes_disabled_over_half']}.",
                  f"Margin chosen on first halves: target 5%: D = 1 h {P['chosen_m_1 h_0.05']}, D = 6 h {P['chosen_m_6 h_0.05']}; target 10%: D = 1 h {P['chosen_m_1 h_0.10']}, D = 6 h {P['chosen_m_6 h_0.10']}. Today's bucket: wait p50 {P['current_wait_p50_h']:.2f} h, p90 {P['current_wait_p90_h']:.1f} h, mean delay per dollar {P['current_mean_delay_h_per_dollar']:.3f} h.", "",
                  "| policy | delayed share (all) | first half | second half | delayed transfers | today's bucket: delayed share | median cap ratio at 1 h | at 6 h | sum ratio at 1 h | at 6 h | pooled wait p50 (h) | pooled wait p90 (h) | mean delay per dollar (h, waits capped at 30 d) |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for key, p in P["policies"].items():
            lines.append(f"| {key} | {p['delayed_share']:.3f} | {p['first_half']:.3f} | {p['second_half']:.3f} | {p['delayed_n']} | {p['current_delayed_share']:.3f} | "
                         f"{p['median_cap_ratio']['1 h']:.2f} | {p['median_cap_ratio']['6 h']:.2f} | {p['sum_cap_ratio']['1 h']:.2f} | {p['sum_cap_ratio']['6 h']:.2f} | "
                         f"{p['pooled_wait_p50_h']:.2f} | {p['pooled_wait_p90_h']:.1f} | {p['mean_delay_h_per_dollar']:.3f} |")
        lines.append("")
    open(os.path.join(ROOT, "results", "ccip_rolling_v2.md"), "w", encoding="utf-8").write(nl.join(lines) + nl)
    print(nl.join(lines))


if __name__ == "__main__":
    main()
