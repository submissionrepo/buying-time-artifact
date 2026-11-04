"""Verify the largest hours per transfer, then compute exact sub-hour envelopes.

Usage:
    python -I verify_subhour.py --data <data/wormhole dir> --end 2026-10-15T16:00:00Z
                                [--top 10] [--max-hours 60] [--max-pairs 80]

Input: <data>/analysis/tops_portal_clean_hourly.csv (Token Bridge series with the CCTP v2
correction and the event exclusion, from analyze_flows.py --adjust), the event rows of
<data>/adjustments.csv, <data>/governor/governed_tokens_union.csv, governor settings.

Step 1, verification.  For each main chain and scope (full history, since the first
Governor release, last 365 days) the K largest hours are checked against their individual
transfers, repeating until the K largest hours of the corrected series are all checked.
Per hour: Token Bridge messages from the chain's Token Bridge emitter (download_vaas.py),
DefiLlama values (value_transfers.py) and, for hours from 2024 on, the API's per-transfer
USD values (/api/v1/operations; earlier records lack them).  Each transfer gets a value on
the hourly API's scale: its API value if known, else its DefiLlama value times the hour's
ratio r (clipped to [0.5, 2]); value the hour total cannot place on a known transfer is
spread evenly over the transfers without a value.  Transfers of tokens never on the
Governor's token list (governor_tokens.py) are removed: the Governor does not meter them.
Removals are written to <data>/adjustments_unlisted.csv (same columns as adjustments.csv).

Step 2, sub-hour envelopes.  A window of length L <= 1 h lies inside some pair of adjacent
hour buckets, and its value is at most the pair's total P(h) = x(h) + x(h+1).  Pairs are
visited in decreasing P(h); for each, the maximum over continuous windows of length L is
computed from the transfers; the search stops when P(h) is below the best window found
for the smallest L (or after max-pairs pairs, in which case the result is a lower bound
and the next P(h) an upper bound).  Output: <data>/analysis/subhour_envelope.csv and
<data>/analysis/verified_hours.csv.  Times are source-chain timestamps.
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import download_vaas as dv  # noqa: E402
import value_transfers as vt  # noqa: E402

MAIN = {1: "Solana", 2: "Ethereum", 4: "BNB Chain", 5: "Polygon", 6: "Avalanche",
        21: "Sui", 22: "Aptos", 23: "Arbitrum", 30: "Base"}
H = pd.Timedelta(hours=1)
GOVERNOR_START = pd.Timestamp("2022-08-17T00:00:00Z")
OPS = "https://api.wormholescan.io/api/v1/operations"
L_MIN = [10, 30, 60]


def fmt(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class HourData:
    def __init__(self, data, union, events, sleep):
        self.data, self.union, self.events, self.sleep = data, union, events, sleep
        self.manifest = dv.load_manifest(data)
        self.ops_calls = []
        self.cache = {}

    def ops_usd(self, cid, h):
        """API per-transfer USD values for the hour, keyed by sequence (classic emitter only)."""
        d = self.data / "raw_ops" / f"{cid}_{fmt(h).replace(':', '')}"
        d.mkdir(parents=True, exist_ok=True)
        out, page = {}, 0
        while page < 50:
            p = d / f"page_{page:04d}.json"
            if p.exists():
                ops = json.loads(p.read_text(encoding="utf-8"))
            else:
                params = {"sourceChain": cid, "appId": "PORTAL_TOKEN_BRIDGE", "from": fmt(h), "to": fmt(h + H),
                          "pageSize": 100, "page": page}
                t0 = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                status, js, url = dv.fetch(OPS, params)
                time.sleep(self.sleep)
                self.ops_calls.append({"url": url, "status": status, "accessed_utc": t0})
                if status != 200:
                    break
                ops = js.get("operations", [])
                p.write_text(json.dumps([{"sequence": o.get("sequence"),
                                          "emitter": (o.get("emitterAddress") or {}).get("hex", ""),
                                          "usd": (o.get("data") or {}).get("usdAmount"),
                                          "symbol": (o.get("data") or {}).get("symbol")} for o in ops]),
                             encoding="utf-8")
                ops = json.loads(p.read_text(encoding="utf-8"))
            for o in ops:
                if o["emitter"].lower() == dv.EMITTER[cid] and o["usd"] is not None:
                    out[str(o["sequence"])] = (float(o["usd"]), o["symbol"])
            if len(ops) < 100:
                break
            page += 1
        return out

    def hour(self, cid, h, api_value):
        """Transfers of chain cid in hour h with values on the API scale; removal of unlisted."""
        key = (cid, h)
        if key in self.cache:
            return self.cache[key]
        try:
            recs, _ = dv.fetch_window(cid, fmt(h), fmt(h + H), self.data / "raw_vaas", self.manifest,
                                      "hour", self.sleep)
        except RuntimeError as e:
            print(f"  fetch failed for chain {cid} {fmt(h)}: {e}", flush=True)
            recs = []
        tr = pd.DataFrame(recs, columns=dv.COLS)
        if len(tr):
            tr, _ = vt.value(tr.astype({"amount_norm": str}), self.data / "llama_price_cache.json", verbose=False)
            tr["t"] = pd.to_datetime(tr["ts"], utc=True, format="ISO8601")
            ev = self.events.get(cid, set())
            tr = tr[~tr["t"].isin(ev)]
            tr["addr"] = tr["token_address_hex"].astype(str).str.lower().str.removeprefix("0x").str.rjust(64, "0")
            tr["listed"] = [(int(c), a) in self.union for c, a in zip(tr["token_chain"], tr["addr"])]
            ops = self.ops_usd(cid, h) if h >= pd.Timestamp("2024-01-01T00:00:00Z") else {}
            tr["usd_api"] = [ops.get(str(s), (None, None))[0] for s in tr["sequence"]]
            tr["symbol_api"] = [ops.get(str(s), (None, None))[1] for s in tr["sequence"]]
            known_api = tr["usd_api"].notna()
            ll = tr["usd_llama"].where(~known_api)
            rest = api_value - float(tr.loc[known_api, "usd_api"].sum())
            ll_sum = float(ll.sum(skipna=True))
            r = min(2.0, max(0.5, rest / ll_sum)) if ll_sum > 0 and rest > 0 else 1.0
            v = tr["usd_api"].where(known_api, tr["usd_llama"] * r)
            unknown = v.isna()
            resid = api_value - float(v.sum(skipna=True))
            if unknown.any():
                v = v.where(~unknown, max(resid, 0.0) / int(unknown.sum()))
            tr["v"] = v.astype(float)
            removal = float(tr.loc[~tr["listed"], "v"].sum())
            tr = tr.sort_values("t")
        else:
            r, resid, removal = 1.0, api_value, 0.0
        res = {"tr": tr, "r": r, "resid_unplaced": resid if len(tr) == 0 else max(0.0, float(api_value - tr["v"].sum())),
               "removal": removal, "n": int(len(tr))}
        self.cache[key] = res
        return res


def max_window(ts_ns, v, L_ns):
    if len(ts_ns) == 0:
        return 0.0, None
    c = np.concatenate([[0.0], np.cumsum(v)])
    j = np.searchsorted(ts_ns, ts_ns + L_ns, side="left")
    s = c[j] - c[np.arange(len(ts_ns))]
    k = int(np.argmax(s))
    return float(s[k]), int(ts_ns[k])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default="2021-09-01T00:00:00Z")
    ap.add_argument("--end", required=True)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--max-hours", type=int, default=60)
    ap.add_argument("--max-pairs", type=int, default=80)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()
    data = Path(args.data)
    out = data / "analysis"
    end = pd.Timestamp(args.end)
    hours = pd.date_range(pd.Timestamp(args.start), end - H, freq="h")
    df = pd.read_csv(out / "tops_portal_clean_hourly.csv")
    df["hour"] = pd.to_datetime(df["hour_utc"], utc=True)
    X = df.pivot_table(index="hour", columns="emitter_chain", values="volume_usd", aggfunc="sum").reindex(hours).fillna(0.0)
    X.columns = [int(c) for c in X.columns]
    union = set()
    for r in pd.read_csv(data / "governor" / "governed_tokens_union.csv").itertuples():
        union.add((int(r.chain), str(r.addr).lower()))
    adj = pd.read_csv(data / "adjustments.csv")
    adj = adj[adj["reason"].astype(str).str.startswith("event:")]
    events = {}
    for r in adj.itertuples():
        events.setdefault(int(r.chain_id), set()).add(pd.Timestamp(r.source_ts))
    hd = HourData(data, union, events, args.sleep)

    scopes = {"full": hours[0], "since_governor": GOVERNOR_START, "last365": end - pd.Timedelta(days=365)}
    removal = {}          # (cid, hour) -> usd removed (unlisted tokens)
    verified = []
    for cid, name in MAIN.items():
        if cid not in X.columns:
            continue
        x0 = X[cid].copy()
        for scope, s0 in scopes.items():
            n_checked = 0
            while n_checked < args.max_hours:
                x = x0.copy()
                for (c, h), d in removal.items():
                    if c == cid:
                        x[h] = max(0.0, x[h] - d)
                xs = x[x.index >= s0]
                top = xs.sort_values(ascending=False).head(args.top)
                todo = [h for h in top.index if (cid, h) not in hd.cache and top[h] > 0]
                if not todo:
                    break
                for h in todo:
                    res = hd.hour(cid, h, float(x0[h]))
                    n_checked += 1
                    removal[(cid, h)] = res["removal"]
                    tr = res["tr"]
                    big = tr.sort_values("v", ascending=False).head(1) if len(tr) else None
                    verified.append({
                        "chain": name, "chain_id": cid, "scope_first_checked": scope, "hour_utc": fmt(h),
                        "api_value_usd": float(x0[h]), "n_transfers": res["n"],
                        "n_unlisted": int((~tr["listed"]).sum()) if len(tr) else 0,
                        "removed_unlisted_usd": res["removal"], "corrected_usd": float(x0[h]) - res["removal"],
                        "r_llama_to_api": res["r"], "unplaced_usd": res["resid_unplaced"],
                        "largest_usd": float(big["v"].iloc[0]) if big is not None and len(big) else None,
                        "largest_symbol": (big["symbol_api"].iloc[0] if big is not None and len(big) and
                                           isinstance(big["symbol_api"].iloc[0], str) else
                                           (str(big["llama_key"].iloc[0]).split(":")[0] + ":token"
                                            if big is not None and len(big) else None)),
                        "largest_listed": bool(big["listed"].iloc[0]) if big is not None and len(big) else None,
                    })
                    print(f"  {name} {fmt(h)} api {x0[h] / 1e6:.2f}M n={res['n']} removed {res['removal'] / 1e6:.2f}M",
                          flush=True)
    dv.save_manifest(data, hd.manifest)
    rows = []
    for (c, h), d in removal.items():
        if d > 0:
            rows.append({"chain_id": c, "hour_utc": fmt(h), "source_ts": "", "token_chain": "", "token_amount": "",
                         "usd_llama": "", "r": "", "delta_usd": d, "reason": "unlisted:token never on the Governor list"})
    pd.DataFrame(rows, columns=["chain_id", "hour_utc", "source_ts", "token_chain", "token_amount", "usd_llama", "r",
                                "delta_usd", "reason"]).to_csv(data / "adjustments_unlisted.csv", index=False)
    pd.DataFrame(verified).to_csv(out / "verified_hours.csv", index=False)

    # Step 2: sub-hour envelopes by branch and bound over adjacent-hour pairs
    sub = []
    for cid, name in MAIN.items():
        if cid not in X.columns:
            continue
        x = X[cid].copy()
        for (c, h), d in removal.items():
            if c == cid:
                x[h] = max(0.0, x[h] - d)
        for scope, s0 in scopes.items():
            xs = x[x.index >= s0]
            vals = xs.to_numpy()
            if len(vals) < 2:
                continue
            P = vals[:-1] + vals[1:]
            order = np.argsort(-P)
            best = {L: (0.0, None) for L in L_MIN}
            examined, exact, unplaced = 0, True, 0.0
            for k in order:
                if P[k] <= best[L_MIN[0]][0] or P[k] <= 0:
                    break
                if examined >= args.max_pairs:
                    exact = False
                    break
                h0, h1 = xs.index[k], xs.index[k + 1]
                parts = []
                for hh in (h0, h1):
                    if x[hh] <= 0:
                        continue
                    res = hd.hour(cid, hh, float(X[cid][hh]))
                    tr = res["tr"]
                    unplaced += res["resid_unplaced"]
                    if len(tr):
                        parts.append(tr[tr["listed"]][["t", "v"]])
                pt = pd.concat(parts).sort_values("t") if parts else pd.DataFrame(columns=["t", "v"])
                ts = pt["t"].dt.as_unit("ns").astype("int64").to_numpy() if len(pt) else np.array([], dtype=np.int64)
                v = pt["v"].to_numpy(dtype=float) if len(pt) else np.array([])
                for L in L_MIN:
                    m, t0 = max_window(ts, v, L * 60 * 10**9)
                    if m > best[L][0]:
                        best[L] = (m, t0)
                examined += 1
            nxt = float(P[order[examined]]) if (not exact and examined < len(order)) else None
            for L in L_MIN:
                m, t0 = best[L]
                sub.append({"chain": name, "chain_id": cid, "scope": scope, "L_minutes": L, "E_usd": m,
                            "window_start_utc": fmt(pd.Timestamp(t0, tz="UTC")) if t0 else None,
                            "pairs_examined": examined, "exact": exact, "upper_bound_if_not_exact": nxt,
                            "unplaced_usd_in_examined_hours": unplaced})
            print(f"  {name} {scope}: E(10m) {best[10][0] / 1e6:.2f}M E(30m) {best[30][0] / 1e6:.2f}M "
                  f"E(60m) {best[60][0] / 1e6:.2f}M pairs {examined} exact {exact}", flush=True)
    dv.save_manifest(data, hd.manifest)
    ops_log = data / "ops_manifest.json"
    old = json.loads(ops_log.read_text(encoding="utf-8")).get("calls", []) if ops_log.exists() else []
    ops_log.write_text(json.dumps({"endpoint": OPS, "calls": old + hd.ops_calls}, indent=1), encoding="utf-8")
    pd.DataFrame(sub).to_csv(out / "subhour_envelope.csv", index=False)
    print("done")


if __name__ == "__main__":
    sys.exit(main())
