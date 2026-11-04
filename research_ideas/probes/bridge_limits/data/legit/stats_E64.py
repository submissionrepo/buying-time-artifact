"""Summary statistics for E64.csv and the checks in its README (prints aggregates only; writes raw/E64/summary.json).
Run: python -I data/legit/stats_E64.py
"""
import collections
import datetime
import json
import pathlib
import sys

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE / "raw" / "E64"
LEGIT = HERE
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(LEGIT))
import collect_E64 as C  # noqa: E402
import summarize_legit  # noqa: E402

iso = C.iso


def main():
    out = {"summarize_legit": summarize_legit.summarize("E64")}
    rows = json.loads((RAW / "rows_all.json").read_text())
    rel = [r for r in rows if r["cls"] == "release" and not r["exclude"]]
    win = [r for r in rows if C.T_START <= r["ts"] <= C.T_END]
    txs_rel = collections.Counter(r["txid"] for r in rel)
    txs_win = {r["txid"] for r in win}
    out["federation_txs_in_window"] = len(txs_win)
    out["txs_with_release"] = len(txs_rel)
    out["txs_without_release"] = len(txs_win - set(txs_rel))
    out["releases_per_tx"] = dict(sorted(collections.Counter(txs_rel.values()).items()))
    out["btc_released"] = round(sum(r["btc"] for r in rel), 8)
    out["distinct_recipients"] = len({r["to"] for r in rel})
    rc = collections.Counter()
    for r in rel:
        rc[r["to"]] += r["usd"]
    tot = sum(rc.values())
    top = rc.most_common(10)
    out["top1_recipient_usd_share"] = round(top[0][1] / tot, 4)
    out["top10_recipient_usd_share"] = round(sum(v for _, v in top) / tot, 4)
    # request (sidechain peg-out record) to payout delay
    d = sorted(r["ts"] - r["peg_time"] for r in rel if r.get("peg_time"))
    q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))]  # noqa: E731
    out["request_to_payout_s"] = {"min": d[0], "p10": q(d, .1), "p50": q(d, .5), "p90": q(d, .9), "p99": q(d, .99), "max": d[-1]}
    out["requests_before_window_paid_in_window"] = sum(1 for r in rel if r["peg_time"] < C.T_START)
    # outside-window exclusions near the failure
    out["excluded_at_or_after_failure"] = [{"ts": iso(r["ts"]), "btc": r["btc"], "matched_pegout_record": r["matched"]}
                                           for r in rows if r["cls"] == "release" and r["exclude"] == "at_or_after_failure"]
    nfs = [r for r in rows if r["cls"] == "release"]
    out["last_release_before_failure"] = iso(max(r["ts"] for r in rel))
    # monthly comparison: Bitcoin payouts (by Bitcoin time) vs sidechain peg-out records (by sidechain time)
    pegs = C.pegs_list(C.T_START - 21 * 86400)
    pm = collections.defaultdict(lambda: [0.0, 0.0, 0, 0])
    for e in pegs:
        m = datetime.datetime.fromtimestamp(e["blocktime"], datetime.timezone.utc).strftime("%Y-%m")
        if e["amount"] > 0:
            pm[m][0] += e["amount"] / 1e8
            pm[m][2] += 1
        else:
            pm[m][1] += -e["amount"] / 1e8
            pm[m][3] += 1
    api = {x["date"][:7]: int(x["amount"]) / 1e8 for x in C.cached(RAW / "liquid" / "pegs_month.json", [])}
    bm = collections.defaultdict(lambda: [0.0, 0, 0.0])
    for r in rel:
        m = datetime.datetime.fromtimestamp(r["ts"], datetime.timezone.utc).strftime("%Y-%m")
        bm[m][0] += r["btc"]
        bm[m][1] += 1
        bm[m][2] += r["usd"]
    months = sorted(set(pm) | set(bm))
    out["monthly"] = {m: {"btc_payouts_in_window": round(bm[m][0], 4), "n_payouts_in_window": bm[m][1],
                          "usd_payouts_in_window": round(bm[m][2]),
                          "sidechain_pegout_records_btc": round(pm[m][1], 4), "n_pegout_records": pm[m][3],
                          "sidechain_pegin_records_btc": round(pm[m][0], 4), "n_pegin_records": pm[m][2],
                          "crawl_net_btc": round(pm[m][0] - pm[m][1], 4), "api_month_net_btc": api.get(m)}
                      for m in months}
    res = {x["date"][:7]: int(x["amount"]) / 1e8 for x in C.cached(RAW / "liquid" / "reserves_month.json", [])}
    out["reserves_month_api_btc"] = {m: res[m] for m in sorted(res) if m >= "2026-03"}
    # daily and hourly
    df = pd.read_csv(LEGIT / "E64.csv")
    df["t"] = pd.to_datetime(df["ts_utc"])
    daily = df.groupby(df.t.dt.floor("D")).usd.sum().reindex(
        pd.date_range(pd.Timestamp(iso(C.T_START)).floor("D"), pd.Timestamp(iso(C.T_END)).floor("D"), freq="D"), fill_value=0)
    out["daily_usd"] = {"median": round(daily.median()), "mean": round(daily.mean()), "p90": round(daily.quantile(.9)),
                        "max": round(daily.max()), "zero_days": int((daily == 0).sum()), "n_days": len(daily)}
    gaps = df.t.sort_values().diff().dropna()
    out["longest_gap_h"] = round(gaps.max().total_seconds() / 3600, 2)
    i = gaps.idxmax()
    s = df.t.sort_values()
    out["longest_gap_end"] = str(s.loc[i])
    out["gap_window_start_to_first_h"] = round((df.t.min() - pd.Timestamp(iso(C.T_START))).total_seconds() / 3600, 2)
    out["gap_last_to_window_end_h"] = round((pd.Timestamp(iso(C.T_END)) - df.t.max()).total_seconds() / 3600, 2)
    top5 = df.sort_values("usd", ascending=False).head(5)
    out["top5"] = top5[["ts_utc", "amount", "usd"]].to_dict("records")
    h = df.groupby(df.t.dt.floor("h")).usd.agg(["sum", "size"]).sort_values("sum", ascending=False).head(3)
    out["top_hours_usd"] = {str(k): [round(v["sum"]), int(v["size"])] for k, v in h.iterrows()}
    dd = df.groupby(df.t.dt.floor("D")).usd.agg(["sum", "size"]).sort_values("sum", ascending=False).head(3)
    out["top_days_usd"] = {str(k)[:10]: [round(v["sum"]), int(v["size"])] for k, v in dd.iterrows()}
    out["usd_quantiles"] = {p: round(df.usd.quantile(p), 2) for p in (0.1, 0.5, 0.9, 0.99)}
    out["btc_quantiles"] = {p: round(df.amount.quantile(p), 8) for p in (0.1, 0.5, 0.9, 0.99)}
    # price check near the failure: hourly series vs the price used in incidents.csv
    pts = C.pricing.chart(C.COIN, min(r["ts"] for r in rel), max(r["ts"] for r in rel), "1h", RAW / "prices", search_width=1800)
    out["price_points_hourly"] = len(pts)
    out["price_last_point"] = [iso(pts[-1][0]), pts[-1][1]]
    out["price_range_window"] = [round(min(p[1] for p in pts)), round(max(p[1] for p in pts))]
    (RAW / "summary.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: v for k, v in out.items() if k != "summarize_legit"}, indent=1, default=str))


if __name__ == "__main__":
    main()
