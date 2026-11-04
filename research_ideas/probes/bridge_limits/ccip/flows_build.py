"""Stage A/B: build the token-transfer table from crawled CCIP API pages and rank token-lanes.

build : read data/ccip/messages_all/page_*.json.gz and data/ccip/messages_lane/*/page_*.json.gz,
        de-duplicate by messageId, map chain selectors to docs chain keys and token addresses to
        symbols/decimals (union over all tokens.json snapshots), write
        data/ccip/derived/transfers.csv.gz (one row per message carrying a token).
rank  : token-lane USD volume over the global-crawl window, with DefiLlama daily prices;
        writes data/ccip/derived/lane_ranking.csv and coverage.json.

Run: python -I flows_build.py build|rank
"""
import collections
import csv
import datetime as dt
import glob
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import ccip_common as cc  # noqa: E402

HIST = os.path.join(cc.DATA, "lanes_history")


def ts(s):
    if not s:
        return None
    return int(dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp())


def token_maps():
    """Union over snapshots (newest wins) of (docs chain, addr) -> (symbol, decimals)."""
    manifest = cc.load_json(os.path.join(HIST, "manifest.json"))
    order = sorted(k for k in manifest if k != "current") + ["current"]
    amap = {}
    for s in order:
        p = os.path.join(HIST, s, "tokens.json")
        if os.path.exists(p):
            amap.update(cc.token_address_map(cc.load_json(p)))
    return amap


def iter_pages(pattern):
    for fn in sorted(glob.glob(pattern)):
        try:
            with gzip.open(fn, "rt", encoding="utf-8") as f:
                page = json.load(f)
        except (EOFError, OSError, json.JSONDecodeError) as e:  # page still being written
            print(f"skip unreadable {os.path.basename(fn)}: {type(e).__name__}")
            continue
        yield fn, page


def resolve_unknown(unknown_tok, key2sel, min_count=30):
    """Symbol/decimals for tokens absent from tokens.json, from /v2/tokens/{selector}/{address}.
    Cached in data/ccip/api_tokens.json (keys 'srcKey|address')."""
    import time
    import requests
    path = os.path.join(cc.DATA, "api_tokens.json")
    cache = cc.load_json(path) if os.path.exists(path) else {}
    for (src, addr), n in unknown_tok.most_common():
        if n < min_count:
            break
        k = f"{src}|{addr}"
        if k in cache or not addr or src not in key2sel:
            continue
        url = f"https://api.ccip.chain.link/v2/tokens/{key2sel[src]}/{addr}"
        status, js = None, {}
        try:
            resp = requests.get(url, headers=cc.UA, timeout=60)
            status = resp.status_code
            if status == 200:
                js = resp.json()
        except requests.RequestException:
            pass
        cache[k] = {"symbol": js.get("symbol"), "decimals": js.get("decimals"), "name": js.get("name"),
                    "status": status, "n_messages": n, "accessed_utc": cc.utcnow()}
        json.dump(cache, open(path, "w", encoding="utf-8"), indent=1)
        time.sleep(1.0)
    return cache


def build():
    chains = cc.load_json(os.path.join(cc.DATA, "lanes_current", "chains.json"))
    key2sel, sel2key = cc.selector_maps(chains)
    amap = token_maps()
    seen = set()
    rows = []
    stats = collections.Counter()
    unknown_tok = collections.Counter()
    srcs = [("global", os.path.join(cc.DATA, "messages_all", "page_*.json.gz")),
            ("lane", os.path.join(cc.DATA, "messages_lane", "*", "page_*.json.gz"))]
    window = {}
    for origin, pattern in srcs:
        tmin, tmax = None, None
        for fn, page in iter_pages(pattern):
            for m in page["body"].get("data", []):
                stats[f"{origin}_messages"] += 1
                if m["sourceNetworkInfo"].get("environment") != "mainnet":
                    stats["non_mainnet"] += 1
                    continue
                t = ts(m["sendTimestamp"])
                tmin = t if tmin is None else min(tmin, t)
                tmax = t if tmax is None else max(tmax, t)
                mid = m["messageId"]
                if mid in seen:
                    stats[f"{origin}_duplicates"] += 1
                    continue
                seen.add(mid)
                stats["unique_messages"] += 1
                sta = m.get("sourceTokenAmount")
                if not sta:
                    continue
                stats["token_messages"] += 1
                ssel = str(m["sourceNetworkInfo"]["chainSelector"])
                dsel = str(m["destNetworkInfo"]["chainSelector"])
                src = sel2key.get(ssel, "api:" + m["sourceNetworkInfo"]["name"])
                dst = sel2key.get(dsel, "api:" + m["destNetworkInfo"]["name"])
                addr = cc.norm_addr(sta["tokenAddress"])
                sym, dec = amap.get((src, addr), (None, None))
                if sym is None:
                    unknown_tok[(src, sta["tokenAddress"])] += 1
                rows.append({
                    "message_id": mid, "origin": origin, "status": m.get("status"),
                    "src": src, "dst": dst, "src_sel": ssel, "dst_sel": dsel,
                    "token": sym, "token_addr": sta["tokenAddress"], "decimals": dec,
                    "amount_raw": sta["tokenAmount"],
                    "amount": (int(sta["tokenAmount"]) / 10 ** dec) if dec is not None else None,
                    "send_ts": t, "receipt_ts": ts(m.get("receiptTimestamp")),
                    "has_data": m.get("hasData"),
                })
        window[origin] = {"min_send_ts": tmin, "max_send_ts": tmax}
    os.makedirs(cc.DERIVED, exist_ok=True)
    # resolve tokens missing from the docs directory via the CCIP API token-detail endpoint
    api = resolve_unknown(unknown_tok, key2sel, min_count=30)
    for r in rows:
        if r["token"] is None:
            hit = api.get(f"{r['src']}|{r['token_addr']}")
            if hit and hit.get("symbol") and hit.get("decimals") is not None:
                r["token"] = hit["symbol"] + "*"
                r["decimals"] = hit["decimals"]
                r["amount"] = int(r["amount_raw"]) / 10 ** hit["decimals"]
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(cc.DERIVED, "transfers.csv.gz"), index=False, compression="gzip")
    cov = {"built_utc": cc.utcnow(), "stats": dict(stats), "window": window,
           "unknown_token_top": [[k[0], k[1], v] for k, v in unknown_tok.most_common(30)],
           "n_unknown_token_messages": int(sum(unknown_tok.values()))}
    json.dump(cov, open(os.path.join(cc.DERIVED, "coverage_build.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: cov[k] for k in ("stats", "window", "n_unknown_token_messages")}, indent=1))
    print(cov["unknown_token_top"][:15])


def rank(top_refine=60):
    df = pd.read_csv(os.path.join(cc.DERIVED, "transfers.csv.gz"), compression="gzip",
                     dtype={"amount_raw": str, "src_sel": str, "dst_sel": str})
    g = df[df.origin == "global"].copy()
    t0, t1 = int(g.send_ts.min()), int(g.send_ts.max())
    tokens_cur = cc.load_json(os.path.join(HIST, "current", "tokens.json"))
    # union of tokens across snapshots for coin candidates
    manifest = cc.load_json(os.path.join(HIST, "manifest.json"))
    tok_union = {}
    for s in sorted(k for k in manifest if k != "current") + ["current"]:
        p = os.path.join(HIST, s, "tokens.json")
        if os.path.exists(p):
            for sym, per in cc.load_json(p).items():
                tok_union.setdefault(sym, {}).update(per)
    syms = sorted(set(g.token.dropna()))
    cand = {s: cc.coin_candidates(tok_union, s) for s in syms}
    # tokens resolved through the API (suffix '*'): price by the observed source chain/address
    for s in syms:
        if s.endswith("*"):
            pairs = g[g.token == s][["src", "token_addr"]].drop_duplicates().values.tolist()
            cand[s] = [f"{cc.LLAMA_CHAIN[a]}:{b}" for a, b in pairs if a in cc.LLAMA_CHAIN]
    pr = cc.current_prices(sorted({c for v in cand.values() for c in v}))
    cur_price, coin_of = {}, {}
    for s in syms:
        for c in cand[s]:
            p = pr.get(c)
            if p and p.get("price") and p.get("confidence", 0) >= 0.8:
                cur_price[s], coin_of[s] = p["price"], c
                break
    g["usd_cur"] = g.token.map(cur_price) * g.amount
    lane = g.groupby(["src", "dst", "token"], dropna=False).agg(
        n=("amount", "size"), amount=("amount", "sum"), usd_cur=("usd_cur", "sum")).reset_index()
    lane = lane.sort_values("usd_cur", ascending=False)
    # refine the top candidates with daily historical prices
    top = lane.head(top_refine)
    need = sorted(set(top.token.dropna()) | {s for s in ("USDC", "LINK") if s in coin_of})
    daily = {}
    for s in need:
        if s not in coin_of:
            continue
        pts = cc.chart_prices(coin_of[s], t0 - 86400, t1 + 86400, period="1d")
        if pts:
            k = np.array(sorted(pts))
            daily[s] = (k, np.array([pts[x] for x in k]))
    def usd_hist(row):
        s = row.token
        if s not in daily:
            return np.nan
        k, v = daily[s]
        i = np.clip(np.searchsorted(k, row.send_ts, side="right") - 1, 0, len(k) - 1)
        return v[i] * row.amount
    sub = g[g.token.isin(daily.keys())].copy()
    sub["usd_hist"] = sub.apply(usd_hist, axis=1)
    lh = sub.groupby(["src", "dst", "token"]).usd_hist.sum().rename("usd_hist").reset_index()
    lane = lane.merge(lh, on=["src", "dst", "token"], how="left")
    lane["usd_rank_value"] = lane.usd_hist.fillna(lane.usd_cur)
    lane = lane.sort_values("usd_rank_value", ascending=False)
    lane.to_csv(os.path.join(cc.DERIVED, "lane_ranking.csv"), index=False)
    tot = lane.usd_rank_value.sum()
    lane["share"] = lane.usd_rank_value / tot
    lane["cum_share"] = lane.share.cumsum()
    json.dump({"window_utc": [dt.datetime.fromtimestamp(t0, dt.timezone.utc).isoformat(),
                              dt.datetime.fromtimestamp(t1, dt.timezone.utc).isoformat()],
               "coin_of": coin_of, "n_token_lanes": int(len(lane)),
               "total_usd_rank_value": float(tot),
               "n_transfers_global": int(len(g)),
               "n_transfers_unpriced": int(g.usd_cur.isna().sum()),
               "token_usd_totals_top": g.groupby("token").usd_cur.sum().sort_values(ascending=False)
                   .head(25).to_dict()},
              open(os.path.join(cc.DERIVED, "ranking_meta.json"), "w", encoding="utf-8"), indent=1)
    pd.set_option("display.width", 220)
    print(lane.head(45).to_string())
    print("total", tot)


if __name__ == "__main__":
    {"build": build, "rank": rank}[sys.argv[1]]()
