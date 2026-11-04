"""Per-transfer corrections to the hourly Token Bridge series (input to analyze_series.py).

Usage (2026-10-16 version):
    python -I build_adjustments.py --data <data/wormhole dir> --rules adjustment_rules.json
           [--transfers transfers_all_valued.csv] [--api-values api_values.csv]
           [--covered covered_hours.csv] [--outlier-usd 1e6] [--outlier-ratio 10]
           [--out-full adjustments_full.csv] [--out-small adjustments_small.csv]
           [--out-transfers transfers_classified.csv] [--out-hours hour_valuation.csv]

Hourly series.  A_c(h) = Token Bridge USD value of chain c in hour h from the API's hourly
series: PORTAL_TOKEN_BRIDGE minus CCTP_V2 (from 2025-05 the API counts CCTP v2 transfers
relayed by the Wormhole executor under every appId), as in analyze_flows.py.

Three values per transfer (value_transfers.py with --cg-map, api_values.py):
  market value M   DefiLlama price of the token's chain-specific key, else of the CoinGecko
                   id that the Governor's token list gives for the token, at the midpoint of
                   the transfer's UTC hour.
  Governor value   for a token on the Governor's list in force at the transfer time (release
                   timeline, governor/governed_tokens_release.csv): amount times
                   max(CoinGecko price, configured price), as in governor_prices.go; the
                   CoinGecko price is DefiLlama's price for the list's CoinGecko id, else the
                   chain-specific key's price, else the API's value.
  API value P      the API's own per-transfer USD value (/api/v1/operations; from 2024).
Value on the API's scale v (the amount removed from A_c(h)), in every hour with complete
per-transfer data (covered_hours.csv, collect_transfers.py):
  hours with API values: v = P; an operation listed with no USD value is not in A_c(h), so
      v = 0; a message missing from the operations listing gets v = M.
  other hours: v = M * r, r = A_c(h) / (sum of M over the hour) clipped to [0.5, 2]; if some
      transfer of the hour has no market value, r is clipped to [0.8, 1.25] instead (a
      valuation-scale difference, not the unpriced value) and the rest stays unplaced in
      the hour (residual A_c(h) - sum of v).
Flags per transfer:
  event     matched by a rule in adjustment_rules.json (documented 2022-02-02 event)
  outlier   valuation outlier: v >= outlier-usd and either v > outlier-ratio * M, or no
            market value and the token not on the Governor's list
  listed    token on the Governor's list in force at the transfer time (for transfers
            before the first list, 2022-08-10: on that first list); unlisted tokens are
            neither counted nor delayed by the Governor
  big       listed and Governor value >= the big-transaction size in force (release
            timeline; the first setting with a size for earlier hours, the last one after a
            chain left the config): the Governor delays it 24 h and never counts it
  ge_1m     market value (else API value) >= 1M USD
Series:
  full  (normal flow)          A_c(h) minus event and outlier transfers
  small (below the big-transaction size: what the Governor's 24 h sum meters)
                               full minus unlisted and big transfers
Hours without per-transfer data are left unchanged: their total is below 0.9 * min(tau,
1M USD), so they hold no big transfer up to valuation differences.

Outputs in <data>: the two adjustment files (chain_id, hour_utc, source_ts, token_chain,
token_amount, usd_llama, r, delta_usd, reason), transfers_classified.csv (one row per
transfer in a covered hour; lag_s = Wormholescan indexing time minus source time) and
hour_valuation.csv (one row per covered hour).  No wallet addresses or transaction hashes.
"""
import argparse
import bisect
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ADJ_COLS = ["chain_id", "hour_utc", "source_ts", "token_chain", "token_amount", "usd_llama", "r",
            "delta_usd", "reason"]
FIRST_LIST = pd.Timestamp("2022-08-10T17:00:48Z")


def load_settings(data):
    st = pd.read_csv(data / "governor" / "governor_settings.csv")
    st = st[st["timeline"] == "release"].copy()
    st["start"] = pd.to_datetime(st["start"], utc=True)
    st["end"] = pd.to_datetime(st["end"], utc=True)
    st["governed"] = st["governed"].astype(str).str.lower() == "true"
    return st


def big_at(st, cid, t):
    s = st[(st["chain_id"] == cid) & (st["start"] <= t) & ((st["end"].isna()) | (st["end"] > t))]
    if len(s) and bool(s.iloc[0]["governed"]) and pd.notna(s.iloc[0]["big_tx_size_usd"]):
        return float(s.iloc[0]["big_tx_size_usd"])
    # before the first setting with a big-transaction size: use that first value; after the
    # chain left the config: use the last value
    s2 = st[(st["chain_id"] == cid) & st["governed"] & st["big_tx_size_usd"].notna()].sort_values("start")
    if s2.empty:
        return None
    return float(s2.iloc[0]["big_tx_size_usd"] if t < s2.iloc[0]["start"] else s2.iloc[-1]["big_tx_size_usd"])


def tau_vector(st, cids, ts):
    """big_at for many transfers, evaluated once per (chain, setting interval)."""
    out = np.full(len(ts), np.nan)
    cids = np.asarray(cids)
    for cid in np.unique(cids):
        idx = np.nonzero(cids == cid)[0]
        tt = ts.iloc[idx]
        bounds = sorted({b for b in pd.concat([st.loc[st["chain_id"] == cid, "start"],
                                               st.loc[st["chain_id"] == cid, "end"].dropna()])})
        if not bounds:
            continue
        edges = [pd.Timestamp("2000-01-01", tz="UTC")] + bounds + [pd.Timestamp("2100-01-01", tz="UTC")]
        vals = [big_at(st, int(cid), edges[k]) if k > 0 else big_at(st, int(cid), edges[1] - pd.Timedelta(seconds=1))
                for k in range(len(edges) - 1)]
        pos = np.searchsorted(np.array([e.value for e in edges]), tt.dt.as_unit("ns").astype("int64").to_numpy(),
                              side="right") - 1
        pos = np.clip(pos, 0, len(vals) - 1)
        out[idx] = [np.nan if vals[p] is None else vals[p] for p in pos]
    return out


def list_lookup(data):
    """(chain, addr) -> sorted list of (start_ns, end_ns, decimals, price) on the release timeline."""
    r = pd.read_csv(data / "governor" / "governed_tokens_release.csv", dtype={"addr": str})
    r["s"] = pd.to_datetime(r["start"], utc=True, format="ISO8601").dt.as_unit("ns").astype("int64")
    r["e"] = pd.to_datetime(r["end"], utc=True, format="ISO8601").dt.as_unit("ns")
    r["e"] = r["e"].map(lambda x: np.iinfo(np.int64).max if pd.isna(x) else x.value)
    out = {}
    for c, a, s, e, d, p in zip(r["chain"], r["addr"], r["s"], r["e"], r["decimals"], r["price"]):
        out.setdefault((int(c), str(a).lower()), []).append((int(s), int(e), int(d), float(p)))
    for k in out:
        out[k].sort()
    return out


def hourly_api(data):
    def long(p):
        df = pd.read_csv(p)
        df["hour"] = pd.to_datetime(df["hour_utc"], utc=True)
        return df.groupby(["emitter_chain", "hour"])["volume_usd"].sum()
    a = long(data / "tops_portal_hourly.csv")
    c = long(data / "tops_cctp_v2_hourly.csv")
    return (a - c.reindex(a.index, fill_value=0.0)).clip(lower=0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--transfers", default="transfers_all_valued.csv")
    ap.add_argument("--api-values", default=None)
    ap.add_argument("--covered", default="covered_hours.csv")
    ap.add_argument("--outlier-usd", type=float, default=1e6)
    ap.add_argument("--outlier-ratio", type=float, default=10.0)
    ap.add_argument("--out-full", default="adjustments_full.csv")
    ap.add_argument("--out-small", default="adjustments_small.csv")
    ap.add_argument("--out-transfers", default="transfers_classified.csv")
    ap.add_argument("--out-hours", default="hour_valuation.csv")
    args = ap.parse_args()
    data = Path(args.data)
    rules = json.loads(Path(args.rules).read_text(encoding="utf-8"))

    tr = pd.read_csv(data / args.transfers, dtype={"token_address_hex": str, "amount_norm": str})
    tr["t"] = pd.to_datetime(tr["ts"], utc=True, format="ISO8601")
    tr["hour"] = tr["t"].dt.floor("h")
    tr = tr.drop_duplicates(subset=["chain_id", "sequence"]).reset_index(drop=True)
    cov = pd.read_csv(data / args.covered)
    cov["hour"] = pd.to_datetime(cov["hour_utc"], utc=True)
    covered = set(zip(cov["chain_id"].astype(int), cov["hour"]))
    tr = tr[[(int(c), h) in covered for c, h in zip(tr["chain_id"], tr["hour"])]].reset_index(drop=True)
    api = hourly_api(data)
    usd_cg = pd.to_numeric(tr["usd_cg"], errors="coerce") if "usd_cg" in tr else pd.Series(np.nan, index=tr.index)
    tr["M"] = pd.to_numeric(tr["usd_llama"], errors="coerce").fillna(usd_cg)

    # the API's per-transfer values
    tr["P"] = np.nan
    tr["api_status"] = "no_ops"
    tr["symbol_api"] = None
    ops_hours = set()
    if args.api_values and (data / args.api_values).exists():
        av = pd.read_csv(data / args.api_values)
        av["hour"] = pd.to_datetime(av["hour_utc"], utc=True)
        ops_hours = set(zip(av["chain_id"].astype(int), av["hour"]))
        m = {(int(c), int(s)): (u, y) for c, s, u, y in zip(av["chain_id"], av["sequence"], av["usd_api"],
                                                             av["symbol_api"])}
        P, status, sym = [], [], []
        for c, h, s in zip(tr["chain_id"], tr["hour"], tr["sequence"]):
            if (int(c), h) not in ops_hours:
                P.append(np.nan); status.append("no_ops"); sym.append(None)
                continue
            hit = m.get((int(c), int(s)))
            if hit is None:
                P.append(np.nan); status.append("absent"); sym.append(None)
            else:
                u, y = hit
                P.append(float(u) if pd.notna(u) else np.nan)
                status.append("value" if pd.notna(u) else "null")
                sym.append(y if isinstance(y, str) else None)
        tr["P"], tr["api_status"], tr["symbol_api"] = P, status, sym

    # Governor list in force at the transfer time, configured price, Governor value
    lk = list_lookup(data)
    addr = tr["token_address_hex"].astype(str).str.lower().str.removeprefix("0x").str.rjust(64, "0")
    tns = tr["t"].dt.as_unit("ns").astype("int64").to_numpy()
    first_ns = FIRST_LIST.value
    listed, floor, decl = [], [], []
    for c, a, t in zip(tr["token_chain"], addr, tns):
        iv = lk.get((int(c), a))
        hit = None
        if iv:
            tq = max(int(t), first_ns)
            k = bisect.bisect_right([x[0] for x in iv], tq) - 1
            if k >= 0 and iv[k][0] <= tq < iv[k][1]:
                hit = iv[k]
        listed.append(hit is not None)
        floor.append(hit[3] if hit else np.nan)
        decl.append(hit[2] if hit else np.nan)
    tr["listed"], tr["floor_price"], tr["dec_gov"] = listed, floor, decl
    # Governor value = max(market value, amount * configured price); the market value is the
    # CoinGecko-id price when DefiLlama has it, else the chain-specific key's price
    amt_gov = np.array([int(a) / 10 ** min(8, int(d)) if not np.isnan(d) else np.nan
                        for a, d in zip(tr["amount_norm"], decl)])
    mkt_gov = (usd_cg.where(usd_cg.notna(), pd.to_numeric(tr["usd_llama"], errors="coerce"))
               .fillna(tr["P"]).to_numpy(dtype=float))
    tr["usd_gov"] = np.fmax(mkt_gov, amt_gov * tr["floor_price"].to_numpy(dtype=float))
    tr.loc[~tr["listed"], "usd_gov"] = np.nan
    st = load_settings(data)
    tr["tau"] = tau_vector(st, tr["chain_id"].astype(int).to_numpy(), tr["t"])
    sym_ll = tr["symbol_llama"] if "symbol_llama" in tr else pd.Series([None] * len(tr))
    tr["symbol"] = [a if isinstance(a, str) and a else (b if isinstance(b, str) else None)
                    for a, b in zip(tr["symbol_api"], sym_ll)]
    ia = pd.to_datetime(tr["indexed_at"], utc=True, format="ISO8601", errors="coerce")
    tr["lag_s"] = (ia - tr["t"]).dt.total_seconds()

    # value on the API's scale, hour by hour
    tr["v"] = np.nan
    tr["r"] = np.nan
    hour_rows = []
    for (cid, h), g in tr.groupby(["chain_id", "hour"]):
        a = float(api.get((int(cid), h), 0.0))
        idx = g.index
        M = g["M"]
        if (int(cid), h) in ops_hours:
            v = pd.Series(np.nan, index=idx)
            s_ = g["api_status"]
            v[s_ == "value"] = g.loc[s_ == "value", "P"]
            v[s_ == "null"] = 0.0
            v[s_ == "absent"] = M[s_ == "absent"]
            r = 1.0
        else:
            ms = float(M.sum(skipna=True))
            lo, hi = (0.5, 2.0) if not M.isna().any() else (0.8, 1.25)
            r = min(hi, max(lo, a / ms)) if (ms > 0 and a > 0) else 1.0
            v = M * r
        tr.loc[idx, "v"] = v
        tr.loc[idx, "r"] = r
        hour_rows.append({"chain_id": int(cid), "hour": h, "api_usd": a, "n": int(len(g)),
                          "n_no_market_value": int(M.isna().sum()), "market_sum": float(M.sum(skipna=True)),
                          "has_ops": (int(cid), h) in ops_hours, "r": r, "placed_usd": float(v.sum(skipna=True)),
                          "n_unvalued": int(v.isna().sum())})
    hv = pd.DataFrame(hour_rows)
    seen = set(zip(hv["chain_id"], hv["hour"])) if len(hv) else set()
    extra = [{"chain_id": c, "hour": h, "api_usd": float(api.get((c, h), 0.0)), "n": 0, "n_no_market_value": 0,
              "market_sum": 0.0, "has_ops": (c, h) in ops_hours, "r": 1.0, "placed_usd": 0.0, "n_unvalued": 0}
             for (c, h) in covered if (c, h) not in seen]
    hv = pd.concat([hv, pd.DataFrame(extra)], ignore_index=True)
    hv["residual_usd"] = hv["api_usd"] - hv["placed_usd"]

    tr["c_mkt"] = tr["M"].where(tr["M"].notna(), tr["P"])
    tr["ge_1m"] = tr["c_mkt"] >= 1e6
    tr["event"] = ""
    for rule in rules.get("event_exclusions", []):
        a, b = pd.Timestamp(rule["from"]), pd.Timestamp(rule["to"])
        sel = tr[(tr["chain_id"] == rule["chain_id"]) & (tr["t"] >= a) & (tr["t"] < b) &
                 (tr["token_chain"] == rule["token_chain"]) &
                 (tr["token_address_hex"].str.lower().str.endswith(rule["token_address_hex_suffix"].lower()))]
        if "token_amounts" in rule:
            sel = sel[pd.to_numeric(sel["token_amount"], errors="coerce").round(6)
                      .isin([round(x, 6) for x in rule["token_amounts"]])]
        if len(sel) != rule.get("expect_n", len(sel)):
            print(f"WARNING rule {rule['id']}: matched {len(sel)} transfers, expected {rule['expect_n']}")
        tr.loc[sel.index, "event"] = rule["id"]
    is_event = tr["event"] != ""
    vv = tr["v"]
    tr["outlier"] = (~is_event) & (vv >= args.outlier_usd) & (
        (tr["M"].notna() & (vv > args.outlier_ratio * tr["M"])) | (tr["M"].isna() & ~tr["listed"]))
    tr["big"] = tr["listed"] & (tr["usd_gov"] >= tr["tau"]) & ~is_event & ~tr["outlier"]
    tr["in_full"] = ~is_event & ~tr["outlier"]
    tr["in_small"] = tr["in_full"] & tr["listed"] & ~tr["big"]

    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")

    def adj_rows(mask, reason_fn):
        sub = tr[mask & tr["v"].notna() & (tr["v"] > 0)]
        return pd.DataFrame({"chain_id": sub["chain_id"].astype(int), "hour_utc": sub["hour"].map(fmt),
                             "source_ts": sub["ts"], "token_chain": sub["token_chain"],
                             "token_amount": sub["token_amount"], "usd_llama": sub["M"], "r": sub["r"],
                             "delta_usd": sub["v"], "reason": [reason_fn(r) for r in sub.itertuples()]},
                            columns=ADJ_COLS)

    full = pd.concat([adj_rows(is_event, lambda r: f"event:{r.event}"),
                      adj_rows(tr["outlier"], lambda r: "outlier:valuation")])
    small = pd.concat([full,
                       adj_rows(tr["in_full"] & ~tr["listed"], lambda r: "unlisted:token not on the Governor list"),
                       adj_rows(tr["big"], lambda r: f"big:>= {r.tau:,.0f}")])
    full.to_csv(data / args.out_full, index=False)
    small.to_csv(data / args.out_small, index=False)

    def hsum(mask):
        return tr[mask].groupby(["chain_id", "hour"])["v"].sum()
    for name, mask in (("event_usd", is_event), ("outlier_usd", tr["outlier"]),
                       ("unlisted_usd", tr["in_full"] & ~tr["listed"]), ("big_usd", tr["big"]),
                       ("ge1m_usd", tr["in_full"] & tr["ge_1m"]), ("small_placed_usd", tr["in_small"])):
        s = hsum(mask)
        hv[name] = [float(s.get((c, h), 0.0)) for c, h in zip(hv["chain_id"], hv["hour"])]
    hv["full_usd"] = (hv["api_usd"] - hv["event_usd"] - hv["outlier_usd"]).clip(lower=0.0)
    hv["small_usd"] = (hv["full_usd"] - hv["unlisted_usd"] - hv["big_usd"]).clip(lower=0.0)
    hv["hour_utc"] = hv["hour"].map(fmt)
    hv = hv.sort_values(["chain_id", "hour"])
    hv.drop(columns=["hour"]).to_csv(data / args.out_hours, index=False)

    tr["hour_utc"] = tr["hour"].map(fmt)
    keep = ["chain_id", "hour_utc", "ts", "sequence", "payload_type", "token_chain", "token_address_hex", "symbol",
            "listed", "token_amount", "usd_llama", "usd_cg", "M", "usd_gov", "floor_price", "P", "api_status", "r",
            "v", "c_mkt", "tau", "big", "ge_1m", "outlier", "event", "in_full", "in_small", "to_chain", "lag_s"]
    keep = [k for k in keep if k in tr.columns]
    tr[keep].rename(columns={"P": "usd_api", "v": "v_usd", "M": "usd_mkt"}).to_csv(data / args.out_transfers,
                                                                                   index=False)
    print(f"covered chain-hours {len(hv)}, transfers {len(tr)} "
          f"(API values for {int((tr['api_status'] == 'value').sum())}, listed {int(tr['listed'].sum())})")
    for name, df in (("full", full), ("small", small)):
        print(f"{name}: {len(df)} removals, {df['delta_usd'].sum():,.0f} USD")
        print(df.assign(kind=df["reason"].str.split(":").str[0]).groupby("kind")["delta_usd"].agg(["count", "sum"]))
    print(f"unvalued transfers {int(tr['v'].isna().sum())}; residual |A - placed| summed "
          f"{hv['residual_usd'].abs().sum():,.0f} USD over covered hours")


if __name__ == "__main__":
    sys.exit(main())
