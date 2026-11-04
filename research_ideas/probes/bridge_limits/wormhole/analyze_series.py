"""Envelopes, value shares and Governor usage for the adjusted Token Bridge series.

Usage:
    python -I analyze_series.py --data <data/wormhole dir> --end 2026-10-15T16:00:00Z
                                [--out <data>/flows]

Inputs (data/wormhole): tops_portal_hourly.csv, tops_cctp_v2_hourly.csv, governor/
governor_settings.csv, adjustments_full.csv and adjustments_small.csv, hour_valuation.csv
and transfers_classified.csv (build_adjustments.py), covered_hours.csv.

Series (USD per UTC hour and source chain):
  full   Token Bridge normal flow: PORTAL_TOKEN_BRIDGE minus CCTP_V2, minus the documented
         2022-02-02 event transfers and valuation outliers.
  small  the part below the Governor's big-transaction size: full minus transfers of
         tokens never on the Governor list and minus transfers at or above the size in force.
Scopes: full history (2021-09-01 on; full series only), since the first Governor release
(2022-08-17), the 24 months and the 365 days before the end hour.

Outputs in --out:
  envelope.csv   E(u) = max over start hours of the u-hour sum, its start hour, E(u+1 h),
                 p99 and p99.9 of the u-hour sum (overlapping windows from the chain's
                 first non-zero hour), for u = 1, 2, 3, 6, 12, 24, 48, 72, 168 h.
  shares.csv     per chain and scope: full-series value, value of transfers at or above the
                 big-transaction size (listed tokens), at or above 1M USD, of unlisted tokens,
                 with counts; `complete_big` / `complete_1m` say whether every hour whose
                 total could hold such a transfer has per-transfer data.
  usage.csv      per chain and Governor setting (release timeline) inside the scope: the
                 trailing 24 h sum of the small series against the daily limit in force
                 (max, p99, median ratio; hours above the limit; episodes; longest and median
                 episode); the same maximum for the full series for comparison.
  episodes.csv   every episode (maximal run of hours whose trailing 24 h small-series sum
                 exceeds the limit): start, end, hours, peak ratio, peak sum.
  series_<name>_hourly.csv  the two series for the main chains (hour_utc, chain_id, usd).
  summary.json   all of the above.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_flows as af  # noqa: E402

MAIN = af.MAIN
U_HOURS = af.U_HOURS
GOV = af.GOVERNOR_START
H = pd.Timedelta(hours=1)


def token_bridge_series(data, hours):
    pw, pn = af.load_series(data / "tops_portal_hourly.csv", hours)
    cw, cc = af.load_series(data / "tops_cctp_v2_hourly.csv", hours)
    cw = cw.reindex(columns=pw.columns, fill_value=0.0)
    return (pw - cw).clip(lower=0.0)


def adjusted(wide, path, hours):
    adj = pd.read_csv(path)
    adj["hour"] = pd.to_datetime(adj["hour_utc"], utc=True)
    w, applied = af.apply_adjustments(wide, adj, hours)
    return w


def scopes_for(end, name):
    s = [("since_governor", GOV), ("24m", end - pd.Timedelta(days=730)), ("365d", end - pd.Timedelta(days=365))]
    if name == "full":
        s = [("full", None)] + s
    return s


def envelope_rows(wide, hours, series, end):
    rows = []
    cols = {cid: wide[cid].to_numpy() if cid in wide.columns else np.zeros(len(hours)) for cid in MAIN}
    targets = [(MAIN[c], cols[c]) for c in MAIN] + [("Sum of 9 main chains", sum(cols.values()))]
    for name, x in targets:
        nz = np.nonzero(x)[0]
        if len(nz) == 0:
            continue
        first = int(nz[0])
        for scope, s0 in scopes_for(end, series):
            a = first if s0 is None else max(first, int(hours.searchsorted(s0)))
            seg = x[a:]
            for u in U_HOURS:
                if len(seg) < u + 1:
                    continue
                st = af.window_stats(seg, u)
                up = af.window_stats(seg, u + 1)
                rows.append({"series": series, "chain": name, "scope": scope, "scope_start": hours[a].isoformat(),
                             "u_hours": u, "E_usd": st["E"], "E_start_hour": hours[a + st["argmax"]].isoformat(),
                             "E_u_plus_1h_usd": up["E"], "p99_usd": st["p99"], "p999_usd": st["p999"],
                             "n_windows": st["n_windows"]})
    return rows


def settings_table(data, timeline="release"):
    st = pd.read_csv(data / "governor" / "governor_settings.csv")
    st = st[st["timeline"] == timeline].copy()
    st["start"] = pd.to_datetime(st["start"], utc=True)
    st["end"] = pd.to_datetime(st["end"], utc=True)
    st["governed"] = st["governed"].astype(str).str.lower() == "true"
    return st


def trailing24(x):
    c = np.concatenate([[0.0], np.cumsum(x)])
    idx = np.arange(len(x))
    return c[idx + 1] - c[np.maximum(idx + 1 - 24, 0)]


def runs(mask):
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def usage_rows(small, full, hours, st, end, timeline):
    rows, eps = [], []
    for cid, name in MAIN.items():
        xs = small[cid].to_numpy() if cid in small.columns else np.zeros(len(hours))
        xf = full[cid].to_numpy() if cid in full.columns else np.zeros(len(hours))
        t24s, t24f = trailing24(xs), trailing24(xf)
        for scope, s0 in scopes_for(end, "small"):
            i0 = int(hours.searchsorted(s0))
            for r in st[(st["chain_id"] == cid) & st["governed"]].sort_values("start").itertuples():
                if pd.isna(r.daily_limit_usd):
                    continue
                a = max(i0, int(hours.searchsorted(r.start)))
                b = len(hours) if pd.isna(r.end) else int(hours.searchsorted(r.end))
                if b <= a:
                    continue
                cap = float(r.daily_limit_usd)
                seg, segf = t24s[a:b], t24f[a:b]
                over = seg > cap
                rr = runs(over)
                durs = [j - i for i, j in rr]
                base = {"timeline": timeline, "scope": scope, "chain": name, "chain_id": cid,
                        "setting_start": r.start.isoformat(), "setting_end": "" if pd.isna(r.end) else r.end.isoformat(),
                        "from": hours[a].isoformat(), "to": (hours[b - 1] + H).isoformat(), "hours": int(b - a),
                        "daily_limit_usd": cap, "big_tx_size_usd": r.big_tx_size_usd,
                        "max_t24_usd": float(seg.max()), "max_at_hour": hours[a + int(np.argmax(seg))].isoformat(),
                        "max_ratio": float(seg.max() / cap), "p99_ratio": float(np.percentile(seg, 99) / cap),
                        "median_ratio": float(np.median(seg) / cap), "hours_above_cap": int(over.sum()),
                        "share_hours_above": float(over.mean()), "episodes": len(rr),
                        "longest_episode_h": max(durs) if durs else 0,
                        "median_episode_h": float(np.median(durs)) if durs else 0.0,
                        "max_ratio_full_series": float(segf.max() / cap),
                        "hours_above_cap_full_series": int((segf > cap).sum())}
                rows.append(base)
                for i, j in rr:
                    k = i + int(np.argmax(seg[i:j]))
                    eps.append({"timeline": timeline, "scope": scope, "chain": name, "chain_id": cid,
                                "daily_limit_usd": cap, "start_hour": hours[a + i].isoformat(),
                                "end_hour_excl": (hours[a + j - 1] + H).isoformat(), "hours": j - i,
                                "peak_ratio": float(seg[k] / cap), "peak_t24_usd": float(seg[k]),
                                "peak_hour": hours[a + k].isoformat()})
    return rows, eps


def share_rows(full, hours, hv, trc, end, st):
    rows = []
    hv = hv.copy()
    hv["hour"] = pd.to_datetime(hv["hour_utc"], utc=True)
    cov = set(zip(hv["chain_id"].astype(int), hv["hour"]))
    trc = trc.copy()
    trc["hour"] = pd.to_datetime(trc["hour_utc"], utc=True)
    import select_big_hours as sbh  # noqa: E402
    for cid, name in MAIN.items():
        x = full[cid].to_numpy() if cid in full.columns else np.zeros(len(hours))
        tau = sbh.tau_series(st, cid, hours)
        for scope, s0 in scopes_for(end, "full"):
            a = 0 if s0 is None else int(hours.searchsorted(s0))
            seg = x[a:]
            hrs = hours[a:]
            tot = float(seg.sum())
            # completeness: every hour that could hold a transfer >= tau (>= 1M) is covered
            need_big = np.nonzero(seg >= 0.9 * tau[a:])[0]
            need_1m = np.nonzero(seg >= 0.9 * np.minimum(tau[a:], 1e6))[0]
            miss_big = [k for k in need_big if (cid, hrs[k]) not in cov]
            miss_1m = [k for k in need_1m if (cid, hrs[k]) not in cov]
            g = trc[(trc["chain_id"] == cid) & (trc["hour"] >= hrs[0]) & trc["in_full"]]
            big = g[g["big"]]
            ge1 = g[g["ge_1m"]]
            unl = g[~g["listed"]]
            gv = lambda d: float(d["v_usd"].sum())
            rows.append({"chain": name, "chain_id": cid, "scope": scope, "scope_start": hrs[0].isoformat(),
                         "full_usd": tot, "big_usd": gv(big), "n_big": int(len(big)),
                         "share_big": gv(big) / tot if tot else np.nan,
                         "ge1m_usd": gv(ge1), "n_ge1m": int(len(ge1)), "share_ge1m": gv(ge1) / tot if tot else np.nan,
                         "unlisted_usd_covered": gv(unl), "share_unlisted_covered": gv(unl) / tot if tot else np.nan,
                         "covered_usd": float(sum(seg[k] for k in range(len(seg)) if (cid, hrs[k]) in cov)),
                         "complete_big": len(miss_big) == 0, "uncovered_big_hours": len(miss_big),
                         "uncovered_big_usd": float(seg[miss_big].sum()) if miss_big else 0.0,
                         "complete_1m": len(miss_1m) == 0, "uncovered_1m_hours": len(miss_1m),
                         "uncovered_1m_usd": float(seg[miss_1m].sum()) if miss_1m else 0.0,
                         "largest_transfer_usd": float(g["v_usd"].max()) if len(g) else 0.0})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default="2021-09-01T00:00:00Z")
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    data = Path(args.data)
    out = Path(args.out) if args.out else data / "flows"
    out.mkdir(exist_ok=True)
    end = pd.Timestamp(args.end)
    hours = pd.date_range(pd.Timestamp(args.start), end - H, freq="h")
    tb = token_bridge_series(data, hours)
    full = adjusted(tb, data / "adjustments_full.csv", hours)
    small = adjusted(tb, data / "adjustments_small.csv", hours)
    for name, w in (("full", full), ("small", small)):
        cols = [c for c in MAIN if c in w.columns]
        long = w[cols].stack().reset_index()
        long.columns = ["hour", "chain_id", "usd"]
        long = long[long["usd"] > 0]
        long["hour_utc"] = long["hour"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        long[["hour_utc", "chain_id", "usd"]].to_csv(out / f"series_{name}_hourly.csv", index=False)
    env = pd.DataFrame(envelope_rows(full, hours, "full", end) + envelope_rows(small, hours, "small", end))
    env.to_csv(out / "envelope.csv", index=False)
    st_rel = settings_table(data, "release")
    st_com = settings_table(data, "commit")
    u_rel, e_rel = usage_rows(small, full, hours, st_rel, end, "release")
    u_com, e_com = usage_rows(small, full, hours, st_com, end, "commit")
    usage = pd.DataFrame(u_rel + u_com)
    usage.to_csv(out / "usage.csv", index=False)
    eps = pd.DataFrame(e_rel + e_com)
    eps.to_csv(out / "episodes.csv", index=False)
    hv = pd.read_csv(data / "hour_valuation.csv")
    trc = pd.read_csv(data / "transfers_classified.csv", dtype={"token_address_hex": str, "event": str}, low_memory=False)
    shares = pd.DataFrame(share_rows(full, hours, hv, trc, end, st_rel))
    shares.to_csv(out / "shares.csv", index=False)
    summary = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "grid": {"start": hours[0].isoformat(), "end_exclusive": end.isoformat()},
               "envelope": env.to_dict(orient="records"), "shares": shares.to_dict(orient="records"),
               "usage": usage.to_dict(orient="records"), "episodes": eps.to_dict(orient="records")}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    sys.exit(main())
