"""Hours that can contain a transfer at or above the Governor's big-transaction size.

Usage:
    python -I select_big_hours.py --data <data/wormhole dir> --end 2026-10-15T16:00:00Z
                                  [--start 2021-09-01T00:00:00Z] [--factor 0.9]
                                  [--cctp <data>/tops_cctp_v2_hourly.csv] [--also-usd 1e6]
                                  [--max-gap 6] [--out <csv>]

A transfer of value >= tau can only sit in an hour whose total is >= tau, so per-transfer
data for those hours suffices to remove every big transfer from the hourly series.  tau is
the big-transaction size in force for the chain at that hour (release timeline); before
the chain's first setting with a size, the first size; after the chain left the config,
the last size.  `factor` (default 0.9) lowers the screen to allow for valuation
differences between the API and DefiLlama.

Options added 2026-10-16:
  --cctp      subtract the CCTP v2 hourly series (counted under every appId filter from
              2025-05) so that the screen runs on the Token Bridge series itself.
  --also-usd  screen at factor * min(tau, also_usd), so that every transfer at or above
              also_usd (e.g. 1e6 for the share of value in transfers >= 1M USD) is also
              captured when tau exceeds it.
  --max-gap   merge two runs of selected hours separated by at most this many hours when
              the merged window needs fewer request pages (estimated from the hourly
              counts) than the two runs separately; the gap hours are downloaded too.
  --exclude-windows  skip hours that lie inside the windows of these csv files (already
              requested by an earlier phase).
Consecutive selected hours always form one window.  Writes a windows csv (chain_id, from,
to, purpose, core_from, core_to, est_ops, est_pages, sel_hours) for download_vaas.py.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = {1: "Solana", 2: "Ethereum", 4: "BNB Chain", 5: "Polygon", 6: "Avalanche",
        21: "Sui", 22: "Aptos", 23: "Arbitrum", 30: "Base"}


def tau_series(st, cid, hours):
    s = st[(st["chain_id"] == cid) & st["governed"] & st["big_tx_size_usd"].notna()].sort_values("start")
    tau = np.full(len(hours), np.nan)
    if s.empty:
        return tau
    tau[:] = float(s.iloc[0]["big_tx_size_usd"])
    for r in s.itertuples():
        a = hours.searchsorted(r.start)
        b = len(hours) if pd.isna(r.end) else hours.searchsorted(r.end)
        tau[a:b] = float(r.big_tx_size_usd)
    last = s.iloc[-1]
    if pd.notna(last["end"]):
        tau[hours.searchsorted(last["end"]):] = float(last["big_tx_size_usd"])
    return tau


def load_wide(path, hours):
    df = pd.read_csv(path)
    df["hour"] = pd.to_datetime(df["hour_utc"], utc=True)
    vol = df.pivot_table(index="hour", columns="emitter_chain", values="volume_usd", aggfunc="sum").reindex(hours).fillna(0)
    cnt = df.pivot_table(index="hour", columns="emitter_chain", values="count", aggfunc="sum").reindex(hours).fillna(0)
    vol.columns = [int(c) for c in vol.columns]
    cnt.columns = [int(c) for c in cnt.columns]
    return vol, cnt


def load_settings(data):
    st = pd.read_csv(data / "governor" / "governor_settings.csv")
    st = st[st["timeline"] == "release"].copy()
    st["start"] = pd.to_datetime(st["start"], utc=True)
    st["end"] = pd.to_datetime(st["end"], utc=True)
    st["governed"] = st["governed"].astype(str).str.lower() == "true"
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default="2021-09-01T00:00:00Z")
    ap.add_argument("--end", required=True)
    ap.add_argument("--factor", type=float, default=0.9)
    ap.add_argument("--cctp", default=None, help="CCTP v2 hourly csv to subtract")
    ap.add_argument("--also-usd", type=float, default=None)
    ap.add_argument("--max-gap", type=int, default=0)
    ap.add_argument("--purpose", default="big")
    ap.add_argument("--grid-start", default="2021-09-01T00:00:00Z")
    ap.add_argument("--exclude-windows", default=None,
                    help="comma-separated window csvs whose hours are already requested")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data = Path(args.data)
    hours = pd.date_range(pd.Timestamp(args.grid_start), pd.Timestamp(args.end) - pd.Timedelta(hours=1), freq="h")
    vol, cnt = load_wide(data / "tops_portal_hourly.csv", hours)
    if args.cctp:
        cv, cc = load_wide(args.cctp, hours)
        cv = cv.reindex(columns=vol.columns, fill_value=0.0)
        cc = cc.reindex(columns=cnt.columns, fill_value=0)
        vol = (vol - cv).clip(lower=0.0)
        cnt = (cnt - cc).clip(lower=0)
    st = load_settings(data)
    i0 = int(hours.searchsorted(pd.Timestamp(args.start)))
    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
    done = set()
    for p in (args.exclude_windows.split(",") if args.exclude_windows else []):
        for w in pd.read_csv(p).itertuples():
            for h in pd.date_range(pd.Timestamp(w._2), pd.Timestamp(w.to) - pd.Timedelta(hours=1), freq="h"):
                done.add((int(w.chain_id), h))
    rows = []
    for cid in MAIN:
        if cid not in vol.columns:
            continue
        tau = tau_series(st, cid, hours)
        thr = args.factor * (np.minimum(tau, args.also_usd) if args.also_usd else tau)
        x = vol[cid].to_numpy()
        k = cnt[cid].to_numpy()
        cand = [i for i in np.nonzero(x >= thr)[0] if i >= i0 and (cid, hours[i]) not in done]
        if len(cand) == 0:
            continue
        runs, a = [], cand[0]
        prev = a
        for i in cand[1:]:
            if i != prev + 1:
                runs.append([a, prev, prev - a + 1])
                a = i
            prev = i
        runs.append([a, prev, prev - a + 1])
        pages = lambda a, b: int(np.ceil(max(float(k[a:b + 1].sum()), 1.0) / 100))
        merged = [runs[0]]
        for r in runs[1:]:
            last = merged[-1]
            gap = r[0] - last[1] - 1
            if gap <= args.max_gap and pages(last[0], r[1]) < pages(last[0], last[1]) + pages(r[0], r[1]):
                last[1] = r[1]
                last[2] += r[2]
            else:
                merged.append(r)
        for a, b, nsel in merged:
            n = int(k[a:b + 1].sum())
            rows.append({"chain_id": cid, "from": fmt(hours[a]), "to": fmt(hours[b] + pd.Timedelta(hours=1)),
                         "purpose": args.purpose, "core_from": fmt(hours[a]),
                         "core_to": fmt(hours[b] + pd.Timedelta(hours=1)),
                         "est_ops": n, "est_pages": pages(a, b), "sel_hours": nsel})
    out = pd.DataFrame(rows)
    path = Path(args.out) if args.out else data / "big_hours_windows.csv"
    out.to_csv(path, index=False)
    if len(out):
        summ = out.groupby("chain_id").agg(windows=("from", "count"), sel_hours=("sel_hours", "sum"),
                                           est_pages=("est_pages", "sum"), est_ops=("est_ops", "sum"))
        summ.index = [MAIN[c] for c in summ.index]
        print(summ)
        print("total windows", len(out), "selected hours", int(out["sel_hours"].sum()),
              "est pages", int(out["est_pages"].sum()))


if __name__ == "__main__":
    sys.exit(main())
