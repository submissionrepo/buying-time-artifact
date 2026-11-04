"""Window envelopes and Governor usage-to-limit ratios from hourly Wormhole outflows.

Usage:
    python -I analyze_flows.py --data <data/wormhole dir> --end 2026-10-15T16:00:00Z
                               [--adjust <data>/adjustments.csv]

Inputs (from download_tops.py, governor_history.py, build_adjustments.py):
    <data>/tops_portal_hourly.csv, <data>/tops_all_hourly.csv
    <data>/governor/governor_settings.csv
    adjustments.csv (optional): per-transfer corrections with columns chain_id, hour_utc,
        delta_usd (amount to subtract from that chain-hour), reason.  Applied to both
        series, giving the cleaned series portal_clean and all_clean.
Outputs in <data>/analysis/:
    coverage.json                 per-chain first/last hour, zero-hour runs, all-chain gaps
    envelope_<series>.csv         E(u), its start hour, E(u+1 h), p99 and p99.9 of the
                                  u-window outflow; scopes: full history, since the first
                                  Governor release (2022-08-17), last 365 days, each year
    usage_to_limit_<series>_<timeline>.csv
                                  per chain and Governor setting: trailing-24 h outflow
                                  relative to the cap in force (Token Bridge series)
    exceed_hours_<series>_<timeline>.csv
                                  every hour whose trailing 24 h outflow exceeded the cap
    summary.json                  all of the above in one file

Definitions (hour buckets are UTC, [h, h+1)):
    x_c(h)    USD value of transfers emitted on chain c in hour h (zero if no row).
    S_u(h)    x_c(h) + ... + x_c(h+u-1), the outflow in the u-hour window starting at h.
    E(u)      max_h S_u(h).  For continuous windows of length u hours the envelope lies in
              [E(u), E(u+1)] because a continuous window of length u meets at most u+1 buckets.
    p99,p999  percentiles (linear interpolation) of S_u(h) over all start hours h from the
              chain's first non-zero hour (or the scope start) to the last full window in
              the scope; windows overlap.
    T24(h)    S_24(h-23): the trailing 24 h outflow at the end of hour h; the hour h is
              assigned to the Governor setting in force at time h.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MAIN = {1: "Solana", 2: "Ethereum", 4: "BNB Chain", 5: "Polygon", 6: "Avalanche",
        21: "Sui", 22: "Aptos", 23: "Arbitrum", 30: "Base"}
U_HOURS = [1, 2, 3, 6, 12, 24, 48, 72, 168]
GOVERNOR_START = pd.Timestamp("2022-08-17T00:00:00Z")  # first release with mainnet limits (v2.8.9)


def load_series(path, hours):
    df = pd.read_csv(path)
    df["hour"] = pd.to_datetime(df["hour_utc"], utc=True)
    df = df[(df["hour"] >= hours[0]) & (df["hour"] <= hours[-1])]
    wide = df.pivot_table(index="hour", columns="emitter_chain", values="volume_usd", aggfunc="sum")
    cnt = df.pivot_table(index="hour", columns="emitter_chain", values="count", aggfunc="sum")
    wide = wide.reindex(hours, fill_value=0.0).fillna(0.0)
    cnt = cnt.reindex(hours, fill_value=0).fillna(0)
    wide.columns = [int(c) for c in wide.columns]
    cnt.columns = [int(c) for c in cnt.columns]
    return wide, cnt


def apply_adjustments(wide, adj, hours):
    w = wide.copy()
    applied = []
    for (cid, h), g in adj.groupby(["chain_id", "hour"]):
        cid = int(cid)
        if h not in w.index:
            continue
        if cid not in w.columns:
            w[cid] = 0.0
        before = float(w.at[h, cid])
        delta = float(g["delta_usd"].sum())
        w.at[h, cid] = max(0.0, before - delta)
        applied.append({"chain_id": cid, "hour_utc": h.isoformat(), "before_usd": before, "delta_usd": delta,
                        "after_usd": float(w.at[h, cid]), "reasons": sorted(set(g["reason"]))})
    return w, applied


def zero_runs(mask, hours, min_len):
    """Runs of True in mask with length >= min_len -> list of (start, end_exclusive, length)."""
    runs = []
    m = np.asarray(mask, dtype=bool)
    i, n = 0, len(m)
    while i < n:
        if m[i]:
            j = i
            while j < n and m[j]:
                j += 1
            if j - i >= min_len:
                runs.append((hours[i].isoformat(), (hours[j - 1] + pd.Timedelta(hours=1)).isoformat(), j - i))
            i = j
        else:
            i += 1
    return runs


def window_stats(x, u):
    c = np.concatenate([[0.0], np.cumsum(x)])
    s = c[u:] - c[:-u]          # s[h] = sum x[h:h+u], h = 0..n-u
    if len(s) == 0:
        return None
    k = int(np.argmax(s))
    return {"E": float(s[k]), "argmax": k, "p99": float(np.percentile(s, 99)),
            "p999": float(np.percentile(s, 99.9)), "n_windows": int(len(s))}


def envelope_table(wide, hours, series_name, end):
    rows = []
    cols = {cid: wide[cid].to_numpy() if cid in wide.columns else np.zeros(len(hours)) for cid in MAIN}
    pooled_main = sum(cols.values())
    pooled_all = wide.sum(axis=1).to_numpy()
    targets = [(MAIN[c], cols[c]) for c in MAIN] + [("Sum of 9 main chains", pooled_main), ("Sum of all chains", pooled_all)]
    years = sorted(set(h.year for h in hours))
    for name, x in targets:
        nz = np.nonzero(x)[0]
        if len(nz) == 0:
            continue
        first = int(nz[0])
        scopes = [("full", first, len(x)),
                  ("since_governor", max(first, int(hours.searchsorted(GOVERNOR_START))), len(x)),
                  ("last365", max(first, int(hours.searchsorted(end - pd.Timedelta(days=365)))), len(x))]
        for y in years:
            a = max(first, int(hours.searchsorted(pd.Timestamp(f"{y}-01-01", tz="UTC"))))
            b = int(hours.searchsorted(pd.Timestamp(f"{y + 1}-01-01", tz="UTC")))
            if b > a:
                scopes.append((str(y), a, b))
        for scope, a, b in scopes:
            seg = x[a:b]
            for u in U_HOURS:
                if len(seg) < u + 1:
                    continue
                st = window_stats(seg, u)
                st_up = window_stats(seg, u + 1)
                rows.append({
                    "series": series_name, "chain": name, "scope": scope,
                    "scope_start": hours[a].isoformat(), "scope_end": (hours[b - 1] + pd.Timedelta(hours=1)).isoformat(),
                    "u_hours": u, "E_usd": st["E"], "E_start_hour": hours[a + st["argmax"]].isoformat(),
                    "E_u_plus_1h_usd": st_up["E"], "p99_usd": st["p99"], "p999_usd": st["p999"],
                    "n_windows": st["n_windows"],
                })
    return pd.DataFrame(rows)


def usage_to_limit(wide, hours, settings, timeline, series_name):
    rows, exceed = [], []
    st = settings[(settings["timeline"] == timeline)].copy()
    st["start"] = pd.to_datetime(st["start"], utc=True)
    st["end"] = pd.to_datetime(st["end"], utc=True)
    for cid, name in MAIN.items():
        x = wide[cid].to_numpy() if cid in wide.columns else np.zeros(len(hours))
        nz = np.nonzero(x)[0]
        if len(nz) == 0:
            continue
        first = int(nz[0])
        c = np.concatenate([[0.0], np.cumsum(x)])
        idx = np.arange(len(x))
        t24 = c[idx + 1] - c[np.maximum(idx + 1 - 24, 0)]   # trailing 24 h ending at end of hour h
        for r in st[st["chain_id"] == cid].itertuples():
            if not r.governed:
                continue
            a = max(first, int(hours.searchsorted(r.start)))
            b = len(hours) if pd.isna(r.end) else int(hours.searchsorted(r.end))
            base = {"series": series_name, "timeline": timeline, "chain": name, "chain_id": cid,
                    "start": r.start.isoformat(), "end": "" if pd.isna(r.end) else r.end.isoformat(),
                    "daily_limit_usd": float(r.daily_limit_usd), "big_tx_size_usd": r.big_tx_size_usd}
            if b <= a:
                rows.append({**base, "hours": 0})
                continue
            seg = t24[a:b]
            cap = float(r.daily_limit_usd)
            over = seg > cap
            ep = int(np.sum(over[1:] & ~over[:-1]) + (1 if over[0] else 0))
            for k in np.nonzero(over)[0]:
                exceed.append({"series": series_name, "timeline": timeline, "chain": name, "chain_id": cid,
                               "hour_utc": hours[a + k].isoformat(), "trailing24_usd": float(seg[k]), "cap_usd": cap,
                               "big_tx_size_usd": r.big_tx_size_usd, "hour_usd": float(x[a + k])})
            rows.append({**base, "hours": int(b - a), "max_trailing24_usd": float(seg.max()),
                         "max_at_hour": hours[a + int(np.argmax(seg))].isoformat(),
                         "max_ratio": float(seg.max() / cap), "p99_ratio": float(np.percentile(seg, 99) / cap),
                         "median_ratio": float(np.median(seg) / cap),
                         "hours_above_cap": int(over.sum()), "episodes_above_cap": ep})
    return pd.DataFrame(rows), pd.DataFrame(exceed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default="2021-09-01T00:00:00Z")
    ap.add_argument("--end", required=True, help="exclusive end hour used for the download")
    ap.add_argument("--adjust", default=None)
    args = ap.parse_args()
    data = Path(args.data)
    out = data / "analysis"
    out.mkdir(exist_ok=True)
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    hours = pd.date_range(start, end - pd.Timedelta(hours=1), freq="h")

    summary = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "grid": {"start": hours[0].isoformat(), "end_exclusive": end.isoformat(), "n_hours": len(hours)},
               "u_hours": U_HOURS, "governor_start": GOVERNOR_START.isoformat(),
               "last365_start": (end - pd.Timedelta(days=365)).isoformat()}
    series = {}
    for s in ("portal", "all"):
        p = data / f"tops_{s}_hourly.csv"
        if p.exists():
            series[s] = load_series(p, hours)
    # From 2025-05 the API counts CCTP v2 transfers relayed by the Wormhole executor under
    # every appId filter; the Token Bridge series is PORTAL_TOKEN_BRIDGE minus CCTP_V2.
    pc = data / "tops_cctp_v2_hourly.csv"
    if "portal" in series and pc.exists():
        cw, cc = load_series(pc, hours)
        pw, pn = series["portal"]
        cw = cw.reindex(columns=pw.columns, fill_value=0.0)
        cc = cc.reindex(columns=pn.columns, fill_value=0)
        neg = int(((pw - cw) < -0.01).to_numpy().sum())
        series["portal"] = ((pw - cw).clip(lower=0.0), (pn - cc).clip(lower=0))
        summary["cctp_v2_correction"] = {
            "file": pc.name, "usd_subtracted": float(cw.to_numpy().sum()),
            "chain_hours_with_cctp": int((cw > 0).to_numpy().sum()), "chain_hours_negative_before_clip": neg,
            "first_hour": str(cw.index[(cw.sum(axis=1) > 0).to_numpy()][0]) if (cw.to_numpy().sum() > 0) else None}
    if args.adjust:
        adj = pd.read_csv(args.adjust)
        adj["hour"] = pd.to_datetime(adj["hour_utc"], utc=True)
        summary["adjustments"] = {}
        for s in list(series):
            w, applied = apply_adjustments(series[s][0], adj, hours)
            series[f"{s}_clean"] = (w, series[s][1])
            summary["adjustments"][s] = applied
            long = w.stack()
            long = long[long > 0].reset_index()
            long.columns = ["hour", "emitter_chain", "volume_usd"]
            cnt = series[s][1].stack().reset_index()
            cnt.columns = ["hour", "emitter_chain", "count"]
            long = long.merge(cnt, on=["hour", "emitter_chain"], how="left").fillna({"count": 0})
            long["hour_utc"] = long["hour"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            long[["hour_utc", "emitter_chain", "volume_usd", "count"]].to_csv(
                out / f"tops_{s}_clean_hourly.csv", index=False)

    cov = {}
    for s, (wide, cnt) in series.items():
        tot = wide.sum(axis=1).to_numpy()
        nz = np.nonzero(tot)[0]
        first_all = int(nz[0])
        cov[s] = {"first_hour_any_chain": hours[first_all].isoformat(),
                  "last_hour_any_chain": hours[int(nz[-1])].isoformat(),
                  "all_chain_zero_runs_ge6h": zero_runs(tot[first_all:] == 0, hours[first_all:], 6),
                  "all_chain_zero_hours": int(np.sum(tot[first_all:] == 0)),
                  "chains": {}}
        for cid, name in MAIN.items():
            x = wide[cid].to_numpy() if cid in wide.columns else np.zeros(len(hours))
            k = cnt[cid].to_numpy() if cid in cnt.columns else np.zeros(len(hours))
            nzc = np.nonzero(x)[0]
            if len(nzc) == 0:
                cov[s]["chains"][name] = None
                continue
            a = int(nzc[0])
            seg = x[a:]
            cov[s]["chains"][name] = {
                "chain_id": cid, "first_hour": hours[a].isoformat(), "last_nonzero_hour": hours[int(nzc[-1])].isoformat(),
                "hours_covered": int(len(seg)), "zero_hours": int(np.sum(seg == 0)),
                "zero_share": float(np.mean(seg == 0)),
                "longest_zero_runs": sorted(zero_runs(seg == 0, hours[a:], 1), key=lambda r: -r[2])[:5],
                "total_usd": float(seg.sum()), "total_transfers": int(k[a:].sum()),
                "max_hour_usd": float(seg.max()),
            }
    summary["coverage"] = cov
    (out / "coverage.json").write_text(json.dumps(cov, indent=1), encoding="utf-8")

    env_all = []
    for s, (wide, cnt) in series.items():
        env = envelope_table(wide, hours, s, end)
        env.to_csv(out / f"envelope_{s}.csv", index=False)
        env_all.append(env)
    summary["envelope"] = pd.concat(env_all).to_dict(orient="records") if env_all else []

    settings = pd.read_csv(data / "governor" / "governor_settings.csv")
    settings["governed"] = settings["governed"].astype(str).str.lower() == "true"
    summary["usage_to_limit"] = {}
    for s in ("portal", "portal_clean"):
        if s not in series:
            continue
        wide, _ = series[s]
        for tl in ("release", "commit"):
            u2l, exc = usage_to_limit(wide, hours, settings, tl, s)
            u2l.to_csv(out / f"usage_to_limit_{s}_{tl}.csv", index=False)
            exc.to_csv(out / f"exceed_hours_{s}_{tl}.csv", index=False)
            summary["usage_to_limit"][f"{s}_{tl}"] = u2l.to_dict(orient="records")
            summary.setdefault("exceed_hours_count", {})[f"{s}_{tl}"] = int(len(exc))
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print("wrote", out, "series:", list(series))


if __name__ == "__main__":
    sys.exit(main())
