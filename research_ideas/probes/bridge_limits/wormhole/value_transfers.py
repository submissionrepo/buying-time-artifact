"""Value per-transfer Token Bridge messages with DefiLlama historical prices.

Usage:
    python -I value_transfers.py --data <data/wormhole dir>
                                 [--input transfers_windows.csv] [--output transfers_valued.csv]
                                 [--cache llama_price_cache.json] [--per-hour]
                                 [--cg-map governor/governed_tokens_cg.csv]
                                 [--cg-extra wormhole/extra_cg_ids.csv]

Input: <data>/<input> (download_vaas.py).
Price source: DefiLlama historical price at the midpoint of the transfer's UTC hour, the
price point nearest to it within 6 h.  Default (2026-10-16): GET
https://coins.llama.fi/batchHistorical?coins={key: [unix, ...]}&searchWidth=6h with up to
200 (coin, time) pairs per request, decimals from cached answers or
https://coins.llama.fi/prices/current/<coins>.  With --per-hour: one request
GET https://coins.llama.fi/prices/historical/<unix>/<coins>?searchWidth=6h per hour.
Coin keys:
  EVM origin chains   '<llama chain>:0x<last 20 bytes of the token address>'
  Solana origin       'solana:<base58 mint>'
  Terra classic / Terra 2 native denoms (uusd, uluna; encoded 0x01 + zero-padded denom)
                      via coingecko ids
Other origin chains (Sui, Aptos, Near, Algorand ASA, CW20 tokens, ...) are left unpriced
under these keys.  With --cg-map (governor_token_versions.py output), every token on the
Governor's list is also priced under DefiLlama's 'coingecko:<id>' key with the list's
decimals (columns cg_key, dec_list, price_cg, usd_cg): the Governor itself prices by that
CoinGecko id, and DefiLlama's chain-specific keys have gaps for some bridged tokens.  When
DefiLlama has no price for a bridged or pegged representation's own id (e.g.
'binance-bridged-usdc-bnb-smart-chain', 'usdt0'), its base asset's id is used (cg_alias;
price_cg_source = 'alias').  CoinGecko-id pairs with no price point within 6 h are retried at
a 48 h search width (price_cg_source 'id_48h' or 'alias_48h').  --cg-extra adds CoinGecko
ids for tokens outside the Governor list (each with its evidence), used for market value
only.
Token amount = amount_norm / 10^min(8, decimals): the Token Bridge truncates amounts to
8 decimals.  Output: <data>/<output> (adds llama_key, decimals, token_amount, price,
usd_llama, price_ts, symbol_llama, priced) and <data>/<cache> (raw answers, reused; written
atomically).  Use a separate cache file when another process is pricing at the same time.
Each run appends its request count and UTC start and end times to <data>/llama_manifest.json.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

EVM = {2: "ethereum", 4: "bsc", 5: "polygon", 6: "avax", 7: "oasis", 9: "aurora", 10: "fantom", 13: "klaytn",
       14: "celo", 16: "moonbeam", 23: "arbitrum", 24: "optimism", 25: "xdai", 30: "base", 34: "scroll",
       35: "mantle", 36: "blast", 38: "linea", 39: "berachain", 44: "unichain", 45: "wc"}
NATIVE_DENOM = {(3, "uusd"): ("coingecko:terrausd", 6), (3, "uluna"): ("coingecko:terra-luna", 6),
                (18, "uluna"): ("coingecko:terra-luna-2", 6)}
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b):
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    pad = len(b) - len(b.lstrip(b"\0"))
    return "1" * pad + s


def coin_key(token_chain, addr_hex):
    h = str(addr_hex).lower().removeprefix("0x").rjust(64, "0")
    tc = int(token_chain)
    if tc in EVM:
        return f"{EVM[tc]}:0x{h[-40:]}", None
    if tc == 1:
        return f"solana:{b58encode(bytes.fromhex(h))}", None
    if tc in (3, 18):
        raw = bytes.fromhex(h)
        if raw[0] == 1:          # native denoms are encoded as 0x01 followed by the zero-padded denom
            raw = raw[1:]
        raw = raw.lstrip(b"\0")
        try:
            denom = raw.decode("ascii")
        except UnicodeDecodeError:
            return None, None
        if (tc, denom) in NATIVE_DENOM:
            return NATIVE_DENOM[(tc, denom)]
    return None, None


def cg_alias(cg_id):
    """Base asset of a bridged or pegged representation (CoinGecko ids such as
    'binance-bridged-usdc-bnb-smart-chain', 'arbitrum-bridged-weth-arbitrum-one', 'usdt0'),
    used only when DefiLlama has no price for the representation's own id."""
    if not isinstance(cg_id, str):
        return None
    s = cg_id.lower()
    # BTC-backed wrappers whose own DefiLlama history is sparse (checked 2026-10-16: the API's
    # per-transfer values of 350 stBTC and 330 enzoBTC equal amount times the BTC price)
    explicit = {"lorenzo-wrapped-bitcoin": "wrapped-bitcoin", "lorenzo-stbtc": "wrapped-bitcoin"}
    if s in explicit:
        return explicit[s]
    if not ("bridged" in s or "binance-peg" in s or s == "usdt0"):
        return None
    for pat, base in (("usdc", "usd-coin"), ("usd-coin", "usd-coin"), ("usdt", "tether"), ("tether", "tether"),
                      ("weth", "weth"), ("busd", "binance-usd"), ("wbtc", "wrapped-bitcoin"),
                      ("wrapped-bitcoin", "wrapped-bitcoin")):
        if pat in s:
            return base
    return None


def _save_cache(cache_p, cache):
    tmp = Path(str(cache_p) + ".tmp")
    tmp.write_text(json.dumps(cache), encoding="utf-8")
    for k in range(20):                   # wait out a transient Windows lock on the target
        try:
            os.replace(tmp, cache_p)
            return
        except PermissionError:
            if k == 19:
                raise
            time.sleep(1.5)


def _get_json(url, params=None, tries=5):
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, timeout=90)
            if r.status_code == 200:
                return r.json()
            print(f"  DefiLlama HTTP {r.status_code}; retry {attempt + 1} after {5 * (attempt + 1)}s", flush=True)
        except requests.RequestException as e:
            print(f"  DefiLlama network error {e!r}; retry {attempt + 1}", flush=True)
        time.sleep(5 * (attempt + 1))
    return None


def fetch_batch(pairs, cache, verbose=True, per_request=200, width_s=6 * 3600, suffix=""):
    """Historical prices for many (coin key, unix ts) pairs through
    GET https://coins.llama.fi/batchHistorical?coins={key: [ts, ...]}&searchWidth=<w>h.
    Each pair is answered with the returned price point nearest to ts if it lies within the
    search width (the semantics of /prices/historical), else None, and cached under
    '<ts>|<key><suffix>'.  The answer carries no decimals; see fetch_decimals.  Returns the
    number of requests."""
    by_key = {}
    for k, ts in pairs:
        by_key.setdefault(k, []).append(ts)
    reqs, cur, n = [], {}, 0
    for k, tss in by_key.items():
        for i in range(0, len(tss), 100):
            chunk = tss[i:i + 100]
            if n + len(chunk) > per_request and cur:
                reqs.append(cur)
                cur, n = {}, 0
            cur.setdefault(k, []).extend(chunk)
            n += len(chunk)
    if cur:
        reqs.append(cur)
    for qi, q in enumerate(reqs, 1):
        js = _get_json("https://coins.llama.fi/batchHistorical",
                       {"coins": json.dumps(q), "searchWidth": f"{width_s // 3600}h"})
        time.sleep(0.6)
        if js is None:
            continue                      # left uncached; a rerun asks again
        coins = js.get("coins", {})
        for k, tss in q.items():
            ent = coins.get(k) or {}
            pr = [p for p in (ent.get("prices") or []) if p.get("price") is not None]
            pts = [int(p["timestamp"]) for p in pr]
            for ts in tss:
                best = min(range(len(pts)), key=lambda j: abs(pts[j] - ts)) if pts else None
                if best is not None and abs(pts[best] - ts) <= width_s:
                    p = pr[best]
                    cache[f"{ts}|{k}{suffix}"] = {"price": p["price"], "timestamp": p["timestamp"],
                                                  "confidence": p.get("confidence"), "symbol": ent.get("symbol")}
                else:
                    cache[f"{ts}|{k}{suffix}"] = None
        if verbose and (qi % 20 == 0 or qi == len(reqs)):
            print(f"  batch {qi}/{len(reqs)}", flush=True)
    return len(reqs)


def fetch_decimals(keys, cache, first_ts):
    """Token decimals per coin key: from any cached /prices/historical answer, else
    GET https://coins.llama.fi/prices/current/<coins>, else one /prices/historical call at the
    coin's first needed timestamp.  Stored in the cache as 'dec|<key>'.  Returns requests."""
    known = {}
    for ck, c in cache.items():
        if ck.startswith("dec|"):
            known[ck[4:]] = c
        elif isinstance(c, dict) and c.get("decimals") is not None:
            known[ck.split("|", 1)[1]] = c["decimals"]
    for k, d in known.items():
        cache.setdefault(f"dec|{k}", d)
    need = [k for k in keys if f"dec|{k}" not in cache]
    n_req = 0
    for i in range(0, len(need), 50):
        chunk = need[i:i + 50]
        js = _get_json("https://coins.llama.fi/prices/current/" + ",".join(chunk))
        n_req += 1
        time.sleep(0.6)
        coins = (js or {}).get("coins", {})
        for k in chunk:
            d = (coins.get(k) or {}).get("decimals")
            if d is not None:
                cache[f"dec|{k}"] = d
    for k in [k for k in need if f"dec|{k}" not in cache]:
        ts = first_ts[k]
        js = _get_json(f"https://coins.llama.fi/prices/historical/{ts}/{k}?searchWidth=6h")
        n_req += 1
        time.sleep(0.6)
        if js is None:
            continue
        c = (js.get("coins") or {}).get(k)
        cache[f"dec|{k}"] = c.get("decimals") if c else None
        if c:
            cache.setdefault(f"{ts}|{k}", c)
    return n_req


def value(tr, cache_p, verbose=True, batch=True, cg_map=None):
    """tr: DataFrame with ts, token_chain, token_address_hex, amount_norm.  Returns a copy
    with llama_key, decimals, token_amount, price, usd_llama, priced, price_ts, symbol_llama.
    batch=True uses /batchHistorical (many coins and timestamps per request); batch=False
    sends one /prices/historical request per hour (the original method).
    cg_map (batch only): {(token_chain, 64-hex address): (coingecko id, list decimals)} from
    the Governor token list; adds cg_key, dec_list, price_cg and usd_cg = amount_norm /
    10^min(8, dec_list) * DefiLlama price of 'coingecko:<id>' (the Governor's own price
    source; governor.go caps the list decimals at 8 as the Token Bridge does)."""
    tr = tr.copy()
    tr["t"] = pd.to_datetime(tr["ts"], utc=True, format="ISO8601")
    tr["hour"] = tr["t"].dt.floor("h")
    keys = [coin_key(c, a) for c, a in zip(tr["token_chain"], tr["token_address_hex"])]
    tr["llama_key"] = [k[0] for k in keys]
    fixed = [k[1] for k in keys]
    if cg_map:
        addr = tr["token_address_hex"].astype(str).str.lower().str.removeprefix("0x").str.rjust(64, "0")
        hits = [cg_map.get((int(c), a)) for c, a in zip(tr["token_chain"], addr)]
        tr["cg_key"] = [f"coingecko:{m[0]}" if m and isinstance(m[0], str) and m[0] else None for m in hits]
        tr["dec_list"] = [m[1] if m else None for m in hits]
        tr["cg_alias_key"] = [f"coingecko:{cg_alias(m[0])}" if m and cg_alias(m[0]) else None for m in hits]
    cache_p = Path(cache_p)
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    n_req = 0
    if batch:
        sub = tr[tr["llama_key"].notna()]
        tsv = (sub["hour"].dt.as_unit("s").astype("int64") + 1800).astype(int)
        pairs = {(k, int(t)) for k, t in zip(sub["llama_key"], tsv) if f"{int(t)}|{k}" not in cache}
        if cg_map:
            sc = tr[tr["cg_key"].notna()]
            tsc = (sc["hour"].dt.as_unit("s").astype("int64") + 1800).astype(int)
            pairs |= {(k, int(t)) for k, t in zip(sc["cg_key"], tsc) if f"{int(t)}|{k}" not in cache}
            sa = tr[tr["cg_alias_key"].notna()]
            tsa = (sa["hour"].dt.as_unit("s").astype("int64") + 1800).astype(int)
            pairs |= {(k, int(t)) for k, t in zip(sa["cg_alias_key"], tsa) if f"{int(t)}|{k}" not in cache}
        pairs = sorted(pairs)
        if verbose:
            print(f"  price pairs to fetch: {len(pairs)}", flush=True)
        for i in range(0, len(pairs), 4000):
            n_req += fetch_batch(pairs[i:i + 4000], cache, verbose)
            _save_cache(cache_p, cache)
        first_ts = {}
        for k, t in zip(sub["llama_key"], tsv):
            first_ts.setdefault(k, int(t))
        evm_sol = sorted({k for k in sub["llama_key"] if not k.startswith("coingecko:")})
        n_req += fetch_decimals(evm_sol, cache, first_ts)
        _save_cache(cache_p, cache)
        if cg_map:
            # CoinGecko-id histories of smaller tokens are sparse in DefiLlama: retry the pairs
            # with no point within 6 h at a 48 h search width (cached as '<ts>|<key>|w48')
            wide = set()
            for col in ("cg_key", "cg_alias_key"):
                s2 = tr[tr[col].notna()]
                t2 = (s2["hour"].dt.as_unit("s").astype("int64") + 1800).astype(int)
                wide |= {(k, int(t)) for k, t in zip(s2[col], t2)
                         if cache.get(f"{int(t)}|{k}", 0) is None and f"{int(t)}|{k}|w48" not in cache}
            wide = sorted(wide)
            if verbose:
                print(f"  CoinGecko-id pairs retried at 48 h: {len(wide)}", flush=True)
            for i in range(0, len(wide), 4000):
                n_req += fetch_batch(wide[i:i + 4000], cache, verbose, width_s=48 * 3600, suffix="|w48")
                _save_cache(cache_p, cache)
    for hour, g in ([] if batch else tr[tr["llama_key"].notna()].groupby("hour")):
        ts = int(hour.timestamp()) + 1800
        need = sorted({k for k in g["llama_key"] if f"{ts}|{k}" not in cache})
        for i in range(0, len(need), 40):
            chunk = need[i:i + 40]
            url = f"https://coins.llama.fi/prices/historical/{ts}/{','.join(chunk)}?searchWidth=6h"
            for attempt in range(5):
                try:
                    r = requests.get(url, timeout=60)
                    if r.status_code == 200:
                        coins = r.json().get("coins", {})
                        for k in chunk:
                            cache[f"{ts}|{k}"] = coins.get(k)
                        break
                    time.sleep(5 * (attempt + 1))
                except requests.RequestException:
                    time.sleep(5 * (attempt + 1))
            n_req += 1
            time.sleep(0.6)
            if n_req % 50 == 0:
                _save_cache(cache_p, cache)
                if verbose:
                    print(f"  {n_req} price requests", flush=True)
    _save_cache(cache_p, cache)
    prices, decs, amts, usd, pts, syms = [], [], [], [], [], []
    for k, fx, hr, amt_norm in zip(tr["llama_key"], fixed, tr["hour"], tr["amount_norm"]):
        ts = int(hr.timestamp()) + 1800
        c = cache.get(f"{ts}|{k}") if isinstance(k, str) else None
        dec = fx if fx is not None else (c.get("decimals") if c and c.get("decimals") is not None
                                         else (cache.get(f"dec|{k}") if c else None))
        price = c.get("price") if c else None
        syms.append(c.get("symbol") if c else None)
        if price is not None and dec is not None:
            amt = int(amt_norm) / 10 ** min(8, int(dec))
            prices.append(price); decs.append(dec); amts.append(amt); usd.append(amt * price)
            pts.append(c.get("timestamp"))
        else:
            prices.append(None); decs.append(dec); amts.append(None); usd.append(None); pts.append(None)
    tr["price"], tr["decimals"], tr["token_amount"], tr["usd_llama"], tr["price_ts"] = prices, decs, amts, usd, pts
    tr["symbol_llama"] = syms
    tr["priced"] = tr["usd_llama"].notna()
    if cg_map:
        pc, uc, src = [], [], []
        for k, ka, hr, amt_norm, dl in zip(tr["cg_key"], tr["cg_alias_key"], tr["hour"], tr["amount_norm"],
                                           tr["dec_list"]):
            ts = int(hr.timestamp()) + 1800
            p, s = None, None
            for key, label in ((k, "id"), (ka, "alias"), (k, "id_48h"), (ka, "alias_48h")):
                if not isinstance(key, str):
                    continue
                c = cache.get(f"{ts}|{key}" + ("|w48" if label.endswith("48h") else ""))
                if c and c.get("price") is not None:
                    p, s = c["price"], label
                    break
            pc.append(p)
            src.append(s)
            ok = p is not None and dl is not None and not pd.isna(dl)
            # transfers carry at most 8 decimals; the Governor caps the list decimals at 8 too
            uc.append(int(amt_norm) / 10 ** min(8, int(dl)) * p if ok else None)
        tr["price_cg"], tr["usd_cg"], tr["price_cg_source"] = pc, uc, src
    return tr.drop(columns=["t"]), n_req


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--input", default="transfers_windows.csv")
    ap.add_argument("--output", default="transfers_valued.csv")
    ap.add_argument("--cache", default="llama_price_cache.json")
    ap.add_argument("--per-hour", action="store_true", help="one /prices/historical request per hour")
    ap.add_argument("--cg-map", default=None, help="governor/governed_tokens_cg.csv (batch mode only)")
    ap.add_argument("--cg-extra", default=None,
                    help="csv (path, or relative to --data) of CoinGecko ids for tokens outside the Governor list")
    args = ap.parse_args()
    data = Path(args.data)
    tr = pd.read_csv(data / args.input, dtype={"token_address_hex": str, "amount_norm": str})
    cg_map = None
    if args.cg_map:
        cm = pd.read_csv(data / args.cg_map, dtype={"addr": str})
        cg_map = {(int(c), str(a).lower()): (g, int(d)) for c, a, g, d in
                  zip(cm["chain"], cm["addr"], cm["coingecko_id"], cm["decimals"])}
        if args.cg_extra:
            pe = Path(args.cg_extra) if Path(args.cg_extra).exists() else data / args.cg_extra
            ce = pd.read_csv(pe, dtype={"addr": str})
            for c, a, g, d in zip(ce["chain"], ce["addr"], ce["coingecko_id"], ce["decimals"]):
                cg_map.setdefault((int(c), str(a).lower()), (g, int(d)))
    t0 = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out, n_req = value(tr, data / args.cache, batch=not args.per_hour, cg_map=cg_map)
    t1 = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    mp = data / "llama_manifest.json"
    runs = json.loads(mp.read_text(encoding="utf-8"))["runs"] if mp.exists() else []
    ep = ("https://coins.llama.fi/prices/historical/<unix>/<coins>?searchWidth=6h" if args.per_hour else
          "https://coins.llama.fi/batchHistorical?coins=<json>&searchWidth=6h (48h retry for CoinGecko ids); "
          "https://coins.llama.fi/prices/current/<coins>")
    runs.append({"endpoint": ep,
                 "input": args.input, "cache": args.cache, "requests": n_req, "started_utc": t0, "ended_utc": t1})
    mp.write_text(json.dumps({"runs": runs}, indent=1), encoding="utf-8")
    out.drop(columns=["hour"]).to_csv(data / args.output, index=False)
    msg = f"transfers {len(out)}, priced {int(out['priced'].sum())} ({out['priced'].mean():.1%})"
    if cg_map:
        both = out["usd_llama"].notna() | out["usd_cg"].notna()
        msg += f"; with the CoinGecko id of the Governor list {int(both.sum())} ({both.mean():.1%})"
    print(msg + f"; price requests {n_req}")


if __name__ == "__main__":
    sys.exit(main())
