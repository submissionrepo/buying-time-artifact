"""Summary numbers for a legit release CSV (used in the <ID>_README.md files).

usage: python -I summarize_legit.py <ID>
"""
import collections
import csv
import datetime
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def summarize(ID):
    rows = list(csv.DictReader(open(HERE / f"{ID}.csv", newline="")))
    n = len(rows)
    pr = [r for r in rows if r["priced"] == "yes"]
    usd = sum(float(r["usd"]) for r in pr)
    ts = [datetime.datetime.fromisoformat(r["ts_utc"].replace("Z", "")) for r in rows]
    by_leg = collections.defaultdict(lambda: [0, 0.0, 0])
    by_asset = collections.defaultdict(lambda: [0, 0.0, 0])
    hour = collections.Counter()
    day = collections.Counter()
    hour_n = collections.Counter()
    day_n = collections.Counter()
    for r, t in zip(rows, ts):
        u = float(r["usd"]) if r["priced"] == "yes" else 0.0
        for d, k in ((by_leg, r["leg"]), (by_asset, r["asset"])):
            d[k][0] += 1
            d[k][1] += u
            d[k][2] += r["priced"] == "yes"
        h = t.strftime("%Y-%m-%dT%H:00Z")
        dd = t.strftime("%Y-%m-%d")
        hour[h] += u
        day[dd] += u
        hour_n[h] += 1
        day_n[dd] += 1
    big = max(pr, key=lambda r: float(r["usd"])) if pr else None
    unpriced = collections.Counter(r["asset"] for r in rows if r["priced"] != "yes")
    days_with = len(day)
    gaps = []
    if ts:
        s = sorted(ts)
        for a, b in zip(s, s[1:]):
            if (b - a).total_seconds() > 2 * 86400:
                gaps.append((a.strftime("%Y-%m-%dT%H:%MZ"), b.strftime("%Y-%m-%dT%H:%MZ"), round((b - a).total_seconds() / 86400, 1)))
    usd_sorted = sorted((float(r["usd"]) for r in pr))
    q = lambda p: usd_sorted[min(len(usd_sorted) - 1, int(p * len(usd_sorted)))] if usd_sorted else None  # noqa: E731
    return {
        "n": n, "n_priced": len(pr), "share_priced_count": len(pr) / n if n else None, "usd_priced": usd,
        "first": min(ts).isoformat() + "Z" if ts else None, "last": max(ts).isoformat() + "Z" if ts else None,
        "days_with_releases": days_with,
        "largest": None if big is None else {k: big[k] for k in ("ts_utc", "leg", "asset", "amount", "usd")},
        "median_usd": q(0.5), "p90_usd": q(0.9), "p99_usd": q(0.99),
        "busiest_hour_usd": hour.most_common(1)[0] if hour else None,
        "busiest_hour_count": hour_n.most_common(1)[0] if hour_n else None,
        "busiest_day_usd": day.most_common(1)[0] if day else None,
        "busiest_day_count": day_n.most_common(1)[0] if day_n else None,
        "mean_daily_usd_150d": usd / 150,
        "by_leg": {k: v for k, v in sorted(by_leg.items(), key=lambda x: -x[1][1])},
        "top_assets": sorted(by_asset.items(), key=lambda x: -x[1][1])[:12],
        "unpriced_by_asset": unpriced.most_common(),
        "gaps_over_2d": gaps,
    }


if __name__ == "__main__":
    print(json.dumps(summarize(sys.argv[1]), indent=1, default=str))
