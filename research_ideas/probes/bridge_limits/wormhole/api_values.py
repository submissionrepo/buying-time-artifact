"""The API's own per-transfer USD values for selected hours (from 2024 on).

Usage:
    python -I api_values.py --data <data/wormhole dir> [--hours hour_valuation.csv]
                            [--min-residual 1e5] [--min-share 0.05] [--valued <valued csv>]
                            [--since 2024-01-01T00:00:00Z] [--all] [--sleep 1.0]
                            [--manifest ops_manifest_big.json] [--out api_values.csv]

Endpoint: GET https://api.wormholescan.io/api/v1/operations?sourceChain=<c>
          &appId=PORTAL_TOKEN_BRIDGE&from=<h>&to=<h+1h>&pageSize=100&page=<k>
Records before about 2024 lack USD values, so only hours from --since are requested.
With --hours (hour_valuation.csv of a first build_adjustments.py pass), an hour is
requested when the market valuation does not reproduce the API's hourly total: the
unplaced residual is at least max(min-residual, min-share * hourly API value).  Without
--hours: when some transfer has no DefiLlama price or the ratio of the hourly API value to
the DefiLlama sum lies outside [0.8, 1.25].  With --all: every covered hour.
Pages are cached in <data>/raw_ops/<chain>_<hour>/ in the format of verify_subhour.py
(sequence, emitter, usd, symbol per operation; written atomically).  The output table
<data>/<out> has chain_id, hour_utc, sequence, usd_api, symbol_api for every Token Bridge
operation found in any complete cached hour (including hours cached by verify_subhour.py).
No wallet addresses or transaction hashes.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import download_vaas as dv  # noqa: E402

OPS = "https://api.wormholescan.io/api/v1/operations"
H = pd.Timedelta(hours=1)
DIR = re.compile(r"^(\d+)_(\d{4}-\d{2}-\d{2}T\d{6}Z)$")


def fmt(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def ops_complete(d):
    pages = sorted(Path(d).glob("page_*.json"))
    if not pages:
        return False
    try:
        return len(dv.read_json(pages[-1])) < 100
    except (json.JSONDecodeError, OSError):
        return False


def fetch_hour(data, cid, h, calls, sleep):
    d = data / "raw_ops" / f"{cid}_{fmt(h).replace(':', '')}"
    if ops_complete(d):
        return True
    d.mkdir(parents=True, exist_ok=True)
    page = 0
    while page < 50:
        p = d / f"page_{page:04d}.json"
        if p.exists():
            ops = dv.read_json(p)
        else:
            params = {"sourceChain": cid, "appId": "PORTAL_TOKEN_BRIDGE", "from": fmt(h), "to": fmt(h + H),
                      "pageSize": 100, "page": page}
            t0 = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            status, js, url = dv.fetch(OPS, params)
            time.sleep(sleep)
            calls.append({"url": url, "status": status, "accessed_utc": t0})
            if status != 200:
                return False
            ops = [{"sequence": o.get("sequence"), "emitter": (o.get("emitterAddress") or {}).get("hex", ""),
                    "usd": (o.get("data") or {}).get("usdAmount"), "symbol": (o.get("data") or {}).get("symbol")}
                   for o in js.get("operations", [])]
            dv.write_json_atomic(p, ops)
        if len(ops) < 100:
            return True
        page += 1
    return False


def hourly_api(data):
    def wide(p):
        df = pd.read_csv(p)
        df["hour"] = pd.to_datetime(df["hour_utc"], utc=True)
        return df.groupby(["emitter_chain", "hour"])["volume_usd"].sum()
    a = wide(data / "tops_portal_hourly.csv")
    c = wide(data / "tops_cctp_v2_hourly.csv")
    return (a - c.reindex(a.index, fill_value=0.0)).clip(lower=0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--valued", default="transfers_all_valued.csv")
    ap.add_argument("--hours", default=None, help="hour_valuation.csv: select hours by unplaced residual")
    ap.add_argument("--min-residual", type=float, default=1e5)
    ap.add_argument("--min-share", type=float, default=0.05)
    ap.add_argument("--since", default="2024-01-01T00:00:00Z")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--manifest", default="ops_manifest_big.json")
    ap.add_argument("--out", default="api_values.csv")
    args = ap.parse_args()
    data = Path(args.data)
    since = pd.Timestamp(args.since)
    todo = []
    if args.hours:
        # hour_valuation.csv from a first build_adjustments.py pass: request the hours whose
        # market valuation does not reproduce the API's hourly total
        hv = pd.read_csv(data / args.hours)
        hv["hour"] = pd.to_datetime(hv["hour_utc"], utc=True)
        hv = hv[(hv["hour"] >= since) & (hv["n"] > 0)]
        sel = hv["residual_usd"].abs() >= np.maximum(args.min_residual, args.min_share * hv["api_usd"])
        if args.all:
            sel[:] = True
        todo = list(zip(hv.loc[sel, "chain_id"].astype(int), hv.loc[sel, "hour"]))
    else:
        tr = pd.read_csv(data / args.valued, dtype={"token_address_hex": str, "amount_norm": str})
        tr["t"] = pd.to_datetime(tr["ts"], utc=True, format="ISO8601")
        tr["hour"] = tr["t"].dt.floor("h")
        tr["usd"] = pd.to_numeric(tr["usd_llama"], errors="coerce")
        cov = pd.read_csv(data / "covered_hours.csv")
        cov["hour"] = pd.to_datetime(cov["hour_utc"], utc=True)
        api = hourly_api(data)
        g = tr.groupby(["chain_id", "hour"]).agg(n=("usd", "size"), n_unpriced=("usd", lambda s: int(s.isna().sum())),
                                                 llama=("usd", "sum"))
        for r in cov[cov["hour"] >= since].itertuples():
            key = (int(r.chain_id), r.hour)
            if key not in g.index:
                continue
            n, nu, ll = g.loc[key]
            a = float(api.get(key, 0.0))
            ratio = a / ll if ll > 0 else np.inf
            if args.all or nu > 0 or not (0.8 <= ratio <= 1.25):
                todo.append(key)
    print(f"hours needing API values: {len(todo)}", flush=True)
    mpath = data / args.manifest
    calls = json.loads(mpath.read_text(encoding="utf-8"))["calls"] if mpath.exists() else []
    t0 = time.time()
    for i, (cid, h) in enumerate(todo, 1):
        ok = fetch_hour(data, cid, h, calls, args.sleep)
        if not ok:
            print(f"  incomplete: chain {cid} {fmt(h)}", flush=True)
        if i % 50 == 0 or i == len(todo):
            tmp = mpath.with_name(mpath.name + ".tmp")
            tmp.write_text(json.dumps({"endpoint": OPS, "calls": calls}, indent=1), encoding="utf-8")
            dv.replace_retry(tmp, mpath)
            print(f"[{i}/{len(todo)}] {(time.time() - t0) / 60:.1f} min", flush=True)
    rows = []
    for d in sorted((data / "raw_ops").iterdir()):
        m = DIR.match(d.name)
        if not m or not ops_complete(d):
            continue
        cid = int(m.group(1))
        s = m.group(2)
        hour = f"{s[:13]}:{s[13:15]}:{s[15:17]}Z"
        for p in sorted(d.glob("page_*.json")):
            for o in dv.read_json(p):
                if str(o.get("emitter", "")).lower() != dv.EMITTER.get(cid, "-"):
                    continue
                rows.append({"chain_id": cid, "hour_utc": hour, "sequence": int(o["sequence"]),
                             "usd_api": None if o.get("usd") is None else float(o["usd"]),
                             "symbol_api": o.get("symbol")})
    out = pd.DataFrame(rows, columns=["chain_id", "hour_utc", "sequence", "usd_api", "symbol_api"])
    out = out.drop_duplicates(["chain_id", "sequence"])
    out.to_csv(data / args.out, index=False)
    print(f"API values: {len(out)} operations in {out[['chain_id', 'hour_utc']].drop_duplicates().shape[0]} hours")


if __name__ == "__main__":
    sys.exit(main())
