"""Token-pool rate limits from lanes.json: current table, monthly history, summaries.

Inputs  data/ccip/lanes_history/<date>/{lanes,tokens}.json, manifest.json,
        data/ccip/lanes_current/chains.json
Outputs data/ccip/derived/lanes_current.csv, lanes_history.csv, lanes_summary.json,
        prices_current.json

Run: python -I lanes_table.py
"""
import collections
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402

import ccip_common as cc  # noqa: E402

HIST = os.path.join(cc.DATA, "lanes_history")
LOCKDOWN_RAW = 2  # capacity <= 2 base units, as in the docs' minimal lockdown pattern


def q(arr, ps=(10, 25, 50, 75, 90)):
    arr = np.asarray([x for x in arr if x is not None and not (isinstance(x, float) and math.isnan(x))], float)
    if arr.size == 0:
        return {}
    return {f"p{p}": float(np.percentile(arr, p)) for p in ps} | {"n": int(arr.size), "min": float(arr.min()),
                                                                  "max": float(arr.max())}


def classify(r):
    if not r["out_enabled"]:
        return "disabled"
    if r["out_cap_raw"] <= LOCKDOWN_RAW:
        return "lockdown (cap<=2 base units)"
    if r["out_rate_raw"] == 0 or r["out_cap_raw"] / r["out_rate_raw"] > 365 * 86400:
        return "quota-only (refill > 365 d)"
    return "active"


UNLIMITED_USD = 1e9  # capacities above this are reported separately ("effectively unlimited")


def main():
    manifest = cc.load_json(os.path.join(HIST, "manifest.json"))
    chains = cc.load_json(os.path.join(cc.DATA, "lanes_current", "chains.json"))
    os.makedirs(cc.DERIVED, exist_ok=True)

    snaps = sorted(k for k in manifest if k != "current") + ["current"]
    hist_rows = []
    per_snap = {}
    for s in snaps:
        m = manifest[s]
        if not m.get("lanes_bytes"):
            continue
        lanes = cc.load_json(os.path.join(HIST, s, "lanes.json"))
        tokens = cc.load_json(os.path.join(HIST, s, "tokens.json")) if m.get("tokens_bytes") else {}
        rows = cc.lane_rows(lanes, tokens)
        for r in rows:
            r["snapshot"] = s
            r["commit_date"] = m["commit_date"]
            r["status"] = classify(r)
        per_snap[s] = rows
        hist_rows.extend(rows)

    cur = per_snap["current"]

    # ---------------------------------------------------------------- prices (current)
    tokens_cur = cc.load_json(os.path.join(HIST, "current", "tokens.json"))
    syms = sorted({r["token"] for r in cur})
    cand = {s: cc.coin_candidates(tokens_cur, s) for s in syms}
    allc = sorted({c for v in cand.values() for c in v})
    pr = cc.current_prices(allc)
    price = {}
    for s in syms:
        for c in cand[s]:
            p = pr.get(c)
            if p and p.get("price") and p.get("confidence", 0) >= 0.8:
                price[s] = {"usd": p["price"], "coin": c, "confidence": p.get("confidence"),
                            "timestamp": p.get("timestamp")}
                break
    json.dump({"accessed_utc": cc.utcnow(), "source": "coins.llama.fi/prices/current (confidence>=0.8)",
               "prices": price}, open(os.path.join(cc.DERIVED, "prices_current.json"), "w", encoding="utf-8"),
              indent=1)

    for r in cur:
        p = price.get(r["token"], {}).get("usd")
        r["price_usd"] = p
        r["out_cap_usd"] = r["out_cap"] * p if (p and r["out_cap"] is not None) else None
        r["out_rate_usd_per_h"] = r["out_rate"] * 3600 * p if (p and r["out_rate"] is not None) else None
        r["in_cap_usd"] = r["in_cap"] * p if (p and r["in_cap"] is not None) else None
        r["refill_h"] = (r["out_cap_raw"] / r["out_rate_raw"] / 3600) if (r["out_rate_raw"] > 0) else None
        r["in_refill_h"] = (r["in_cap_raw"] / r["in_rate_raw"] / 3600) if (r["in_rate_raw"]) else None

    # ---------------------------------------------------------------- CSV outputs
    cols = ["snapshot", "commit_date", "src", "dst", "token", "status", "src_decimals", "out_enabled",
            "out_cap_raw", "out_rate_raw", "out_cap", "out_rate", "in_present", "in_enabled", "in_cap_raw",
            "in_rate_raw", "in_decimals", "in_decimals_rule", "in_cap", "in_rate", "src_pool_version",
            "dst_pool_version", "lane_usd_enabled", "lane_usd_cap", "lane_usd_rate"]
    with open(os.path.join(cc.DERIVED, "lanes_history.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(hist_rows)
    cols_cur = cols + ["price_usd", "out_cap_usd", "out_rate_usd_per_h", "in_cap_usd", "refill_h", "in_refill_h"]
    with open(os.path.join(cc.DERIVED, "lanes_current.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols_cur, extrasaction="ignore")
        w.writeheader()
        w.writerows(cur)

    # ---------------------------------------------------------------- current summary
    act = [r for r in cur if r["status"] == "active"]
    S = {"snapshot": manifest["current"], "price_source": "DefiLlama coins API, current price at access",
         "n_entries": len(cur), "n_src_chains": len({r['src'] for r in cur}),
         "n_lanes": len({(r['src'], r['dst']) for r in cur}), "n_tokens": len({r['token'] for r in cur}),
         "status_counts": dict(collections.Counter(r["status"] for r in cur)),
         "in_status": dict(collections.Counter(
             ("absent" if not r["in_present"] else ("enabled" if r["in_enabled"] else "disabled")) for r in cur)),
         "n_active_priced": sum(1 for r in act if r["out_cap_usd"] is not None),
         "n_tokens_priced": len(price)}
    S["refill_h_quantiles_active"] = q([r["refill_h"] for r in act])
    rt = collections.Counter(round(r["refill_h"], 2) for r in act if r["refill_h"] is not None)
    S["refill_h_most_common"] = rt.most_common(12)
    bins = [0, 1 / 60, 10 / 60, 1, 6, 24, 24 * 7, float("inf")]
    labels = ["<1 min", "1-10 min", "10 min-1 h", "1-6 h", "6-24 h", "1-7 d", ">=7 d"]
    hb = collections.Counter()
    for r in act:
        h = r["refill_h"]
        for i in range(len(labels)):
            if bins[i] <= h + 1e-9 < bins[i + 1] or (i == len(labels) - 1 and h >= bins[i]):
                hb[labels[i]] += 1
                break
    S["refill_h_bins_active"] = {k: hb.get(k, 0) for k in labels}
    S["out_cap_usd_quantiles_active"] = q([r["out_cap_usd"] for r in act])
    S["out_rate_usd_per_h_quantiles_active"] = q([r["out_rate_usd_per_h"] for r in act])
    ratio = [r["in_cap"] / r["out_cap"] for r in act
             if r["in_enabled"] and r["in_cap"] and r["out_cap"]]
    S["in_over_out_capacity_quantiles"] = q(ratio, (5, 10, 25, 50, 75, 90, 95))
    S["in_over_out_capacity_share_1.0_to_1.2"] = (sum(1 for x in ratio if 1.0 <= x <= 1.2 + 1e-9) / len(ratio)
                                                   if ratio else None)
    S["in_over_out_capacity_share_below_1"] = (sum(1 for x in ratio if x < 1 - 1e-9) / len(ratio)) if ratio else None
    S["inbound_decimal_rules"] = dict(collections.Counter(r["in_decimals_rule"] for r in cur if r["in_present"]))
    diff = [r for r in act if r["in_present"] and r["in_decimals_rule"] not in ("equal", "missing-decimals")
            and r["in_cap"] and r["out_cap"]]
    S["differing_decimals_active_entries"] = len(diff)
    S["differing_decimals_plausible_ratio_0.5_2"] = sum(1 for r in diff if 0.5 <= r["in_cap"] / r["out_cap"] <= 2)
    # aggregate response b + r d of all active outbound buckets (USD), excluding capacities
    # above UNLIMITED_USD, which are listed separately
    unl = [r for r in act if r["out_cap_usd"] is not None and r["out_cap_usd"] > UNLIMITED_USD]
    S["effectively_unlimited_active"] = [
        {k: r[k] for k in ("src", "dst", "token", "out_cap", "out_rate", "out_cap_usd")} for r in unl]
    agg = {}
    for lab, d in [("0", 0), ("10min", 600), ("1h", 3600), ("6h", 21600), ("24h", 86400)]:
        agg[lab] = sum(r["out_cap_usd"] + r["out_rate_usd_per_h"] * d / 3600
                       for r in act if r["out_cap_usd"] is not None and r["out_cap_usd"] <= UNLIMITED_USD)
    S["sum_active_outbound_response_usd_excl_unlimited"] = agg
    # per-token sum over its outbound buckets (all source chains and lanes) at d = 0 and 24 h:
    # what the CCIP limits allow to leave all pools of one token in one day
    tok = collections.defaultdict(lambda: [0.0, 0.0, 0, None])
    for r in act:
        if r["out_cap_usd"] is None or r["out_cap_usd"] > UNLIMITED_USD:
            continue
        t = tok[r["token"]]
        t[0] += r["out_cap_usd"]
        t[1] += r["out_cap_usd"] + r["out_rate_usd_per_h"] * 24
        t[2] += 1
    S["per_token_sum_outbound_usd_top"] = sorted(
        [{"token": k, "sum_cap_usd": v[0], "sum_response_24h_usd": v[1], "n_buckets": v[2]} for k, v in tok.items()],
        key=lambda x: -x["sum_cap_usd"])[:25]
    top = sorted([r for r in act if r["out_cap_usd"] is not None], key=lambda r: -r["out_cap_usd"])[:20]
    S["top_outbound_capacity_usd"] = [
        {k: r[k] for k in ("src", "dst", "token", "out_cap", "out_rate", "out_cap_usd", "out_rate_usd_per_h",
                           "refill_h", "in_cap", "in_rate")} for r in top]
    by_src = collections.Counter(r["src"] for r in act)
    S["active_by_src_top"] = by_src.most_common(12)
    by_tok_src = collections.defaultdict(list)
    for r in act:
        by_tok_src[r["token"]].append(r)
    S["n_tokens_with_active_bucket"] = len(by_tok_src)

    # ---------------------------------------------------------------- history summary
    H = []
    for s in snaps:
        rows = per_snap.get(s)
        if not rows:
            continue
        a = [r for r in rows if r["status"] == "active"]
        rh = [r["out_cap_raw"] / r["out_rate_raw"] / 3600 for r in a if r["out_rate_raw"] > 0]
        lane_lvl = {(r["src"], r["dst"]): (r["lane_usd_cap"], r["lane_usd_rate"]) for r in rows
                    if r["lane_usd_enabled"]}
        H.append({"snapshot": s, "commit_date": manifest[s]["commit_date"], "n_entries": len(rows),
                  "n_lanes_with_lane_usd_limit": len(lane_lvl),
                  "lane_usd_cap_median": float(np.median([v[0] for v in lane_lvl.values()])) if lane_lvl else None,
                  "lane_usd_cap_max": max([v[0] for v in lane_lvl.values()]) if lane_lvl else None,
                  "inbound_recorded": any(r["in_cap_raw"] is not None for r in rows),
                  "n_src_chains": len({r['src'] for r in rows}), "n_tokens": len({r['token'] for r in rows}),
                  "status": dict(collections.Counter(r["status"] for r in rows)),
                  "refill_h_p25": float(np.percentile(rh, 25)) if rh else None,
                  "refill_h_median": float(np.median(rh)) if rh else None,
                  "refill_h_p75": float(np.percentile(rh, 75)) if rh else None})
    S["history"] = H

    # parameter changes between consecutive snapshots (active entries present in both)
    changes = collections.Counter()
    prev = None
    for s in snaps:
        rows = per_snap.get(s)
        if rows is None:
            continue
        cur_map = {(r["src"], r["dst"], r["token"]): (r["out_enabled"], r["out_cap_raw"], r["out_rate_raw"])
                   for r in rows}
        if prev is not None:
            for k, v in cur_map.items():
                if k in prev:
                    if prev[k] != v:
                        changes[s] += 1
                else:
                    changes[s + " new"] += 1
        prev = cur_map
    S["outbound_param_changes_by_snapshot"] = dict(changes)
    json.dump(S, open(os.path.join(cc.DERIVED, "lanes_summary.json"), "w", encoding="utf-8"), indent=1,
              default=str)
    print(json.dumps({k: S[k] for k in ("n_entries", "n_src_chains", "n_lanes", "status_counts", "in_status",
                                        "n_active_priced", "refill_h_quantiles_active", "refill_h_bins_active",
                                        "out_cap_usd_quantiles_active", "in_over_out_capacity_quantiles",
                                        "inbound_decimal_rules", "differing_decimals_active_entries",
                                        "differing_decimals_plausible_ratio_0.5_2",
                                        "sum_active_outbound_response_usd_excl_unlimited",
                                        "effectively_unlimited_active", "outbound_param_changes_by_snapshot")},
                     indent=1, default=str))
    for h in H:
        print(h["snapshot"], h["commit_date"][:10], h["n_entries"], h["n_src_chains"], h["n_tokens"], h["status"],
              round(h["refill_h_median"] or -1, 2), "laneUSD", h["n_lanes_with_lane_usd_limit"],
              h["lane_usd_cap_median"], h["lane_usd_cap_max"], "in-rec", h["inbound_recorded"])


if __name__ == "__main__":
    main()
