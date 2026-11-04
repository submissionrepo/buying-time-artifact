"""Distribution of the outbound token-pool buckets across all CCIP token-lanes with the outbound limit enabled.

Input   data/ccip/derived/lanes_current.csv (lanes.json of the last commit before access, read by lanes_table.py)
        and prices_current.json (DefiLlama current prices, confidence >= 0.8).
Output  data/ccip/derived/limits_distribution.json

Classes (as in lanes_table.py): near-zero capacity (enabled, capacity <= 2 base units), no refill (capacity/rate
above 365 days), active (all other enabled entries).  Quantiles of capacity and rate in token units pool
different tokens and are only a description of the parameter values; the USD columns use the current price.

Run: python -I limits_distribution.py
"""
import collections
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import ccip_common as cc  # noqa: E402

PS = (5, 10, 25, 50, 75, 90, 95)
CLASS = {"active": "active", "lockdown (cap<=2 base units)": "near-zero capacity",
         "quota-only (refill > 365 d)": "no refill"}


def q(x):
    x = np.asarray([v for v in x if v is not None and not (isinstance(v, float) and math.isnan(v))], float)
    if x.size == 0:
        return {"n": 0}
    return {"n": int(x.size), "min": float(x.min()), "max": float(x.max()), "mean": float(x.mean()),
            **{f"p{p}": float(np.percentile(x, p)) for p in PS}}


def bins(x, edges, labels):
    c = collections.Counter()
    for v in x:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            c["unpriced"] += 1
            continue
        for lo, hi, lab in zip(edges, edges[1:], labels):
            if lo <= v < hi:
                c[lab] += 1
                break
    return {lab: c.get(lab, 0) for lab in labels + ["unpriced"]}


def main():
    c = pd.read_csv(os.path.join(cc.DERIVED, "lanes_current.csv"))
    pr = cc.load_json(os.path.join(cc.DERIVED, "prices_current.json"))
    e = c[c.out_enabled == True].copy()  # noqa: E712
    e["cls"] = e.status.map(CLASS)
    e["refill_s"] = np.where(e.out_rate_raw > 0, e.out_cap_raw / e.out_rate_raw.replace(0, np.nan), np.nan)
    e["rate_usd_h"] = e.out_rate_usd_per_h
    e["rate_usd_d"] = e.out_rate_usd_per_h * 24
    e["rate_over_cap_per_day"] = e.out_rate * 86400 / e.out_cap
    out = {"source": "lanes.json (smartcontractkit/documentation, commit of 2026-10-14) via lanes_table.py",
           "price_source": pr["source"], "price_accessed_utc": pr["accessed_utc"],
           "n_entries": int(len(c)), "n_enabled": int(len(e)), "n_disabled": int((c.out_enabled == False).sum()),  # noqa
           "n_tokens_enabled": int(e.token.nunique()), "n_lanes_enabled": int(e[["src", "dst"]].drop_duplicates().shape[0]),
           "n_src_chains_enabled": int(e.src.nunique()),
           "class_counts": dict(collections.Counter(e.cls))}
    groups = {"all enabled": e, "active": e[e.cls == "active"],
              "active, capacity <= $1B": e[(e.cls == "active") & ~(e.out_cap_usd > 1e9)]}
    stats = {}
    for name, g in groups.items():
        stats[name] = {
            "n": int(len(g)), "n_priced": int(g.out_cap_usd.notna().sum()),
            "capacity_tokens": q(g.out_cap), "rate_tokens_per_s": q(g.out_rate),
            "refill_h": q(g.refill_s / 3600), "capacity_usd": q(g.out_cap_usd),
            "rate_usd_per_h": q(g.rate_usd_h), "rate_usd_per_day": q(g.rate_usd_d),
        }
    out["stats"] = stats
    act = groups["active"]
    out["refill_bins_active"] = bins(list(act.refill_s / 3600),
                                     [0, 1 / 60, 10 / 60, 1 - 1e-6, 1 + 1e-2, 6, 23.5, 24.5, 7 * 24, float("inf")],
                                     ["< 1 min", "1-10 min", "10 min-1 h", "1.00-1.01 h", "1.01-6 h", "6-23.5 h",
                                      "23.5-24.5 h", "24.5 h-7 d", ">= 7 d"])
    out["capacity_usd_bins_active"] = bins(list(act.out_cap_usd),
                                           [0, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, float("inf")],
                                           ["< $1k", "$1k-10k", "$10k-100k", "$100k-1M", "$1M-10M", "$10M-100M",
                                            "$100M-1B", ">= $1B"])
    # most common refill times and (capacity, rate) settings in token units
    rt = collections.Counter(round(x / 3600, 2) for x in act.refill_s if not math.isnan(x))
    out["refill_h_most_common_active"] = rt.most_common(10)
    pairs = collections.Counter(zip(act.token, act.out_cap.round(6), act.out_rate.round(9)))
    out["settings_most_common_active"] = [
        {"token": t, "capacity": b, "rate": r, "refill_h": (b / r / 3600) if r else None, "n_lanes": n}
        for (t, b, r), n in pairs.most_common(15)]
    # per token: how many lanes share one setting (standardized settings across a token's lanes)
    tok_n = act.groupby("token").size()
    tok_set = act.groupby("token").apply(lambda g: g[["out_cap", "out_rate"]].round(9).drop_duplicates().shape[0])
    multi = tok_n[tok_n >= 3].index
    out["tokens_with_3plus_active_lanes"] = int(len(multi))
    out["share_of_those_with_one_setting"] = float((tok_set[multi] == 1).mean()) if len(multi) else None
    # inbound bucket of the destination pool relative to the outbound bucket (enabled pairs)
    both = act[(act.in_enabled == True) & act.in_cap.notna() & (act.out_cap > 0)]  # noqa: E712
    ratio = both.in_cap / both.out_cap
    out["inbound_over_outbound_capacity"] = {**q(ratio), "share_1.0_to_1.2": float(((ratio >= 1.0 - 1e-9) &
                                                                                      (ratio <= 1.2 + 1e-9)).mean())}
    out["inbound_status_enabled_out"] = dict(collections.Counter(
        "absent" if not x.in_present else ("enabled" if x.in_enabled else "disabled") for x in e.itertuples()))
    out["effectively_unlimited_active"] = [
        {"token": x.token, "src": x.src, "dst": x.dst, "capacity": x.out_cap, "capacity_usd": x.out_cap_usd}
        for x in act[act.out_cap_usd > 1e9].itertuples()]
    with open(os.path.join(cc.DERIVED, "limits_distribution.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    print(json.dumps({k: out[k] for k in ("n_entries", "n_enabled", "class_counts", "refill_bins_active",
                                          "capacity_usd_bins_active", "refill_h_most_common_active",
                                          "tokens_with_3plus_active_lanes", "share_of_those_with_one_setting")},
                     indent=1, default=str))
    for name, s in stats.items():
        print(name, s["n"], s["n_priced"], "refill_h", {k: round(v, 3) for k, v in s["refill_h"].items()})
        print("   cap_usd", {k: (round(v) if isinstance(v, float) else v) for k, v in s["capacity_usd"].items()})
        print("   rate_usd_h", {k: (round(v) if isinstance(v, float) else v) for k, v in s["rate_usd_per_h"].items()})


if __name__ == "__main__":
    main()
