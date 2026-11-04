"""Shared helpers for the CCIP rate-limit and flow probes.

Reading of lanes.json (checked against the live CCIP API v2 token-detail
endpoint /v2/tokens/{chainSelector}/{token} on 2026-10-15 for two token
lanes):

  lanes[A][B].supportedTokens[T].rateLimiterConfig describes the token pool on
  chain A for remote chain B.
    out = A's outbound bucket (transfers A -> B), in A's local decimals.
    in  = A's inbound bucket (transfers B -> A).  Pools of version 1.5.x consume
          the inbound bucket with the amount as encoded by the source chain, so
          the bucket is in B's (remote) decimals; pools of version >= 1.6 use
          A's local decimals.
  Hence for a transfer lane A -> B the two buckets that apply are
    lanes[A][B].out  (source pool) and  lanes[B][A].in  (destination pool).
"""
import datetime as dt
import json
import os
import re
import time

import requests

BASE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.path.join(BASE, "data", "ccip")
DERIVED = os.path.join(DATA, "derived")
UA = {"User-Agent": "research-probe/0.1 (academic study of bridge rate limits)"}

# docs chain key -> DefiLlama chain key, in the order we try them for pricing
LLAMA_CHAIN = {
    "mainnet": "ethereum", "ethereum-mainnet-base-1": "base", "ethereum-mainnet-arbitrum-1": "arbitrum",
    "bsc-mainnet": "bsc", "matic-mainnet": "polygon", "avalanche-mainnet": "avax",
    "ethereum-mainnet-optimism-1": "optimism", "solana-mainnet": "solana",
    "ethereum-mainnet-linea-1": "linea", "sonic-mainnet": "sonic", "ethereum-mainnet-mantle-1": "mantle",
    "xdai-mainnet": "xdai", "ethereum-mainnet-zksync-1": "era", "ethereum-mainnet-scroll-1": "scroll",
    "celo-mainnet": "celo", "ethereum-mainnet-mode-1": "mode", "ronin-mainnet": "ronin",
    "berachain-mainnet": "berachain", "ethereum-mainnet-unichain-1": "unichain",
    "ethereum-mainnet-ink-1": "ink", "hyperliquid-mainnet": "hyperliquid", "sei-mainnet": "sei",
    "monad-mainnet": "monad", "plasma-mainnet": "plasma", "ethereum-mainnet-blast-1": "blast",
    "wemix-mainnet": "wemix", "kaia-mainnet": "klaytn", "core-mainnet": "core",
    "ethereum-mainnet-worldchain-1": "wc", "soneium-mainnet": "soneium", "fraxtal-mainnet": "fraxtal",
    "aptos-mainnet": "aptos", "shibarium-mainnet": "shibarium", "xdc-mainnet": "xdc",
    "rootstock-mainnet": "rsk", "cronos-mainnet": "cronos", "bitcoin-mainnet-bob-1": "bob",
    "ethereum-mainnet-taiko-1": "taiko", "polygon-mainnet-katana": "katana",
}
PRICE_PRIORITY = list(LLAMA_CHAIN.keys())


def utcnow():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def version_tuple(type_and_version):
    if not type_and_version:
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", type_and_version)
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def norm_addr(a):
    """EVM addresses are case-insensitive; others (Solana, Aptos...) are kept as-is."""
    if a is None:
        return None
    return a.lower() if a.startswith("0x") else a


def bucket(cfg, side):
    """Bucket (enabled, capacity, rate) in base units.  Snapshots before 2024-11 store one
    bucket per token entry ({capacity, isEnabled, rate}); its values carry over unchanged
    into the later 'out' field, so it is read as the outbound bucket and inbound is None."""
    cfg = cfg or {}
    if "out" not in cfg and "in" not in cfg and "capacity" in cfg:
        if side == "in":
            return None, None, None
        b = cfg
    else:
        b = cfg.get(side) or {}
    return bool(b.get("isEnabled")), int(b.get("capacity", 0) or 0), int(b.get("rate", 0) or 0)


def inbound_decimals(tokens, sym, dst, src):
    """Decimals in which the destination pool's inbound bucket (dst pool, remote src) is
    denominated, plus the rule that was applied."""
    td, ts = tokens.get(sym, {}).get(dst, {}), tokens.get(sym, {}).get(src, {})
    dd, ds = td.get("decimals"), ts.get("decimals")
    if dd is None or ds is None:
        return (dd if dd is not None else ds), "missing-decimals"
    if dd == ds:
        return dd, "equal"
    # Rule inferred from the current lanes.json (active buckets whose decimals differ across
    # the two chains; reading that puts inbound capacity within 0.85-1.3x of the outbound):
    # EVM pools 1.5.1 -> remote decimals in 22 of 25; EVM 1.6.x / 2.x, Solana (0.1.x, 1.6.2)
    # and Aptos pools -> local decimals in 85 of 90.
    v = version_tuple(td.get("typeAndVersion"))
    if v is not None and v[0] == 1 and v[1] == 5:
        return ds, "v1.5-remote"
    if v is not None:
        return dd, "v1.6+/non-EVM-local"
    if "1.6.x" in (td.get("typeAndVersion") or ""):
        return dd, "v1.6+/non-EVM-local"
    return None, "unknown-version"


def lane_rows(lanes, tokens):
    """One row per (src, dst, token) entry of lanes.json with both applicable buckets."""
    rows = []
    for src, dsts in lanes.items():
        for dst, lane in dsts.items():
            for sym, ent in (lane.get("supportedTokens") or {}).items():
                cfg = (ent or {}).get("rateLimiterConfig") or {}
                oe, oc, orate = bucket(cfg, "out")
                dec_src = tokens.get(sym, {}).get(src, {}).get("decimals")
                rev = (((lanes.get(dst) or {}).get(src) or {}).get("supportedTokens") or {}).get(sym)
                if rev is not None:
                    ie, ic, irate = bucket((rev or {}).get("rateLimiterConfig"), "in")
                else:
                    ie, ic, irate = None, None, None
                dec_in, rule = inbound_decimals(tokens, sym, dst, src)
                # plausibility: when decimals differ and the version rule is unknown, pick the
                # reading that puts the inbound capacity closest to the outbound capacity.
                if ic is not None and dec_in is None and dec_src is not None and oc > 0:
                    dd = tokens.get(sym, {}).get(dst, {}).get("decimals")
                    cands = [d for d in (dec_src, dd) if d is not None]
                    oc_u = oc / 10 ** dec_src
                    dec_in = min(cands, key=lambda d: abs((ic / 10 ** d) / oc_u - 1.0) if ic else 0)
                    rule = "closest-to-outbound"
                rows.append({
                    "src": src, "dst": dst, "token": sym,
                    "src_decimals": dec_src,
                    "out_enabled": oe, "out_cap_raw": oc, "out_rate_raw": orate,
                    "out_cap": (oc / 10 ** dec_src) if dec_src is not None else None,
                    "out_rate": (orate / 10 ** dec_src) if dec_src is not None else None,
                    "in_present": rev is not None,
                    "in_enabled": ie, "in_cap_raw": ic, "in_rate_raw": irate,
                    "in_decimals": dec_in, "in_decimals_rule": rule,
                    "in_cap": (ic / 10 ** dec_in) if (ic is not None and dec_in is not None) else None,
                    "in_rate": (irate / 10 ** dec_in) if (irate is not None and dec_in is not None) else None,
                    "lane_usd_enabled": bool((lane.get("rateLimiterConfig") or {}).get("isEnabled")),
                    "lane_usd_cap": int((lane.get("rateLimiterConfig") or {}).get("capacity", 0) or 0) / 1e18,
                    "lane_usd_rate": int((lane.get("rateLimiterConfig") or {}).get("rate", 0) or 0) / 1e18,
                    "src_pool_version": (tokens.get(sym, {}).get(src, {}) or {}).get("typeAndVersion"),
                    "dst_pool_version": (tokens.get(sym, {}).get(dst, {}) or {}).get("typeAndVersion"),
                })
    return rows


def selector_maps(chains):
    """docs key <-> chain selector (string)."""
    key2sel = {k: str(v["chainSelector"]) for k, v in chains.items() if "chainSelector" in v}
    sel2key = {v: k for k, v in key2sel.items()}
    return key2sel, sel2key


def token_address_map(tokens):
    """(docs chain key, normalized token address) -> symbol, decimals."""
    out = {}
    for sym, per in tokens.items():
        for ch, e in per.items():
            a = norm_addr(e.get("tokenAddress"))
            if a:
                out[(ch, a)] = (sym, e.get("decimals"))
    return out


# ------------------------------------------------------------------ prices (DefiLlama)
PRICE_CACHE = os.path.join(DATA, "prices")


def _get(url, params=None, tries=8):
    wait = 3.0
    for _ in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=90)
        except requests.RequestException:
            time.sleep(wait)
            wait = min(wait * 2, 120)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(wait)
            wait = min(wait * 2, 120)
            continue
        raise RuntimeError(f"{r.status_code} {url} {r.text[:200]}")
    raise RuntimeError(f"retries exhausted {url}")


def coin_candidates(tokens, sym):
    per = tokens.get(sym, {})
    out = []
    for ch in PRICE_PRIORITY:
        if ch in per and per[ch].get("tokenAddress"):
            out.append(f"{LLAMA_CHAIN[ch]}:{per[ch]['tokenAddress']}")
    return out


def current_prices(coins, sleep=1.0):
    """coins: list of 'chain:address'.  Returns {coin: {price, symbol, timestamp, confidence}}."""
    os.makedirs(PRICE_CACHE, exist_ok=True)
    res = {}
    for i in range(0, len(coins), 40):
        chunk = coins[i:i + 40]
        js = _get("https://coins.llama.fi/prices/current/" + ",".join(chunk), {"searchWidth": "6h"})
        res.update(js.get("coins", {}))
        time.sleep(sleep)
    return res


def chart_prices(coin, start_ts, end_ts, period="1h", sleep=1.0):
    """Price series for one coin between start_ts and end_ts (unix seconds).  Cached per coin/period."""
    os.makedirs(PRICE_CACHE, exist_ok=True)
    step = {"1h": 3600, "1d": 86400}[period]
    fn = os.path.join(PRICE_CACHE, re.sub(r"[^A-Za-z0-9_.-]", "_", f"{coin}_{period}.json"))
    cache = load_json(fn) if os.path.exists(fn) else {"coin": coin, "period": period, "points": {}}
    pts = cache["points"]
    t = start_ts
    while t < end_ts:
        span = min(500, int((end_ts - t) // step) + 1)
        key = f"{t}:{span}"
        if key not in cache.setdefault("fetched", []):
            js = _get(f"https://coins.llama.fi/chart/{coin}",
                      {"start": t, "span": span, "period": period, "searchWidth": "600" if period == "1h" else "43200"})
            for c in js.get("coins", {}).values():
                for p in c.get("prices", []):
                    pts[str(p["timestamp"])] = p["price"]
            cache["fetched"].append(key)
            cache["accessed_utc"] = utcnow()
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            time.sleep(sleep)
        t += span * step
    return {int(k): v for k, v in pts.items()}
