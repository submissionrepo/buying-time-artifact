"""Choose time windows for the per-transfer check (download_ops.py input).

Usage:
    python -I select_windows.py --data <data/wormhole dir> --end 2026-10-15T16:00:00Z
                                [--hourly <hourly csv>] [--exceed <exceed_hours csv>]
                                [--top1h 3] [--max-pages 1500]

Writes <data>/ops_windows_request.csv (chain_id, from, to, purpose, est_ops, est_pages).
Windows, per main chain, from the Token Bridge hourly series:
  peak1h_<scope>_<k>  the k-th largest hour bucket (non-overlapping), extended by 1 h on
                      each side so that continuous 60-min windows across bucket edges
                      are covered; scope = full history or last 365 days.
  peak24h_<scope>     the 24 h window attaining E(24 h), extended by 1 h on each side.
  exceed_<k>          an episode of hours whose trailing 24 h outflow exceeded the cap in
                      force (release timeline), from 23 h before its first hour to the end
                      of its last hour, so that trailing sums can be recomputed per transfer.
Episodes are added in order of their peak ratio while the page budget lasts; skipped
episodes are listed in <data>/ops_windows_skipped.csv.
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = {1: "Solana", 2: "Ethereum", 4: "BNB Chain", 5: "Polygon", 6: "Avalanche",
        21: "Sui", 22: "Aptos", 23: "Arbitrum", 30: "Base"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default="2021-09-01T00:00:00Z")
    ap.add_argument("--end", required=True)
    ap.add_argument("--top1h", type=int, default=3)
    ap.add_argument("--max-pages", type=int, default=1500)
    ap.add_argument("--hourly", default=None, help="hourly CSV to rank (default <data>/tops_portal_hourly.csv)")
    ap.add_argument("--exceed", default=None, help="exceedance CSV (default none)")
    args = ap.parse_args()
    data = Path(args.data)
    end = pd.Timestamp(args.end)
    hours = pd.date_range(pd.Timestamp(args.start), end - pd.Timedelta(hours=1), freq="h")
    df = pd.read_csv(args.hourly or (data / "tops_portal_hourly.csv"))
    df["hour"] = pd.to_datetime(df["hour_utc"], utc=True)
    vol = df.pivot_table(index="hour", columns="emitter_chain", values="volume_usd", aggfunc="sum").reindex(hours).fillna(0)
    cnt = df.pivot_table(index="hour", columns="emitter_chain", values="count", aggfunc="sum").reindex(hours).fillna(0)
    l365 = hours.searchsorted(end - pd.Timedelta(days=365))
    H = pd.Timedelta(hours=1)
    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")

    def est(cid, a, b):
        ia, ib = hours.searchsorted(a), hours.searchsorted(b)
        n = float(cnt[cid].iloc[ia:ib].sum()) if cid in cnt.columns else 0.0
        return int(n), int(np.ceil(n / 100)) + 1

    wins = []
    for cid in MAIN:
        if cid not in vol.columns:
            continue
        x = vol[cid].to_numpy()
        for scope, a0 in (("full", 0), ("last365", l365)):
            seg = x[a0:]
            order = np.argsort(-seg)
            picked = []
            for k in order:
                if seg[k] <= 0 or len(picked) >= args.top1h:
                    break
                if any(abs(int(k) - p) <= 2 for p in picked):
                    continue
                picked.append(int(k))
            for rank, k in enumerate(picked, 1):
                h = hours[a0 + k]
                a, b = h - H, h + 2 * H
                n, p = est(cid, a, b)
                wins.append({"chain_id": cid, "from": fmt(a), "to": fmt(b), "purpose": f"peak1h_{scope}_{rank}",
                             "core_from": fmt(h), "core_to": fmt(h + H), "est_ops": n, "est_pages": p})
            c = np.concatenate([[0.0], np.cumsum(seg)])
            s = c[24:] - c[:-24]
            k = int(np.argmax(s))
            h = hours[a0 + k]
            a, b = h - H, h + 25 * H
            n, p = est(cid, a, b)
            wins.append({"chain_id": cid, "from": fmt(a), "to": fmt(b), "purpose": f"peak24h_{scope}",
                         "core_from": fmt(h), "core_to": fmt(h + 24 * H), "est_ops": n, "est_pages": p})

    # de-duplicate identical windows (full and last365 can coincide)
    seen, uniq = set(), []
    for w in wins:
        key = (w["chain_id"], w["from"], w["to"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(w)
    wins = uniq

    exc_path = Path(args.exceed) if args.exceed else None
    skipped = []
    if exc_path is not None and exc_path.exists() and exc_path.stat().st_size > 5:
        exc = pd.read_csv(exc_path)
        exc["hour"] = pd.to_datetime(exc["hour_utc"], utc=True)
        eps_rows = []
        for cid, g in exc.groupby("chain_id"):
            g = g.sort_values("hour")
            ep_id = (g["hour"].diff() > H).cumsum()
            for _, run in g.groupby(ep_id):
                first, last = run["hour"].iloc[0], run["hour"].iloc[-1]
                peak = float((run["trailing24_usd"] / run["cap_usd"]).max())
                a, b = first - 23 * H, last + H
                n, p = est(int(cid), a, b)
                eps_rows.append({"chain_id": int(cid), "from": fmt(a), "to": fmt(b), "purpose": "exceed",
                                 "core_from": fmt(first), "core_to": fmt(last + H), "est_ops": n, "est_pages": p,
                                 "peak_ratio": peak, "hours": len(run)})
        eps_rows.sort(key=lambda r: -r["peak_ratio"])
        budget = args.max_pages - sum(w["est_pages"] for w in wins)
        for k, e in enumerate(eps_rows, 1):
            e["purpose"] = f"exceed_{k}"
            if e["est_pages"] <= budget:
                wins.append(e)
                budget -= e["est_pages"]
            else:
                skipped.append(e)
    cols = ["chain_id", "from", "to", "purpose", "core_from", "core_to", "est_ops", "est_pages", "peak_ratio", "hours"]
    for path, rows in ((data / "ops_windows_request.csv", wins), (data / "ops_windows_skipped.csv", skipped)):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in cols})
    print(f"windows {len(wins)} (est pages {sum(w['est_pages'] for w in wins)}), skipped episodes {len(skipped)} "
          f"(est pages {sum(e['est_pages'] for e in skipped)})")


if __name__ == "__main__":
    sys.exit(main())
