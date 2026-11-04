"""Release timings read on the receiving side (2026-10-16).

Used for events whose custody is spread over many addresses (deposit addresses, hot wallets) or
whose custody contract is not public: the release path is the sequence of inflows to the
recipient addresses that the sources name.
- EVM native coin: trace_filter with toAddress = recipients (calls with value > 0).
- EVM tokens: Transfer logs with topic2 = a recipient.
- Bitcoin: confirmed transactions paying a recipient address (mempool.space REST API).
Selection: rows whose sender is in `from_only` when given; rows from `exclude_from` dropped;
token rows outside a leg's `tokens_only` list or inside its `exclude_tokens` list (look-alike
tokens that emit spoofed Transfer events) dropped; rows below
`min_usd` dropped after pricing.
USD at the time: DefiLlama coins API at the first row (searchWidth 6h), as in 02_onchain_timing.py.

Input  data/incidents/onchain_targets.json, entries with "mode": "inflow"
Output data/incidents/onchain/<target>.json (raw rows, with hashes) and the target's entry in
       data/incidents/onchain_summary.json (no addresses or hashes).
Run: python -I incidents/04_onchain_inflows.py <target_id> [...]
"""
import datetime
import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rpc import Rpc, TRANSFER, topic_addr, addr_from_topic, erc20_meta  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "incidents"
CONFIG = DATA / "onchain_targets.json"
OUTDIR = DATA / "onchain"
SUMMARY = DATA / "onchain_summary.json"
PRICES = DATA / "prices"

LLAMA_CHAIN = {"ethereum": "ethereum", "bsc": "bsc", "polygon": "polygon", "arbitrum": "arbitrum",
               "base": "base", "fantom": "fantom", "avalanche": "avax", "optimism": "optimism"}
NATIVE_ID = {"ethereum": "coingecko:ethereum", "bsc": "coingecko:binancecoin",
             "polygon": "coingecko:matic-network", "arbitrum": "coingecko:ethereum",
             "base": "coingecko:ethereum", "optimism": "coingecko:ethereum",
             "fantom": "coingecko:fantom", "avalanche": "coingecko:avalanche-2",
             "bitcoin": "coingecko:bitcoin"}
HORIZONS = (600, 3600, 21600, 86400)
CHAIN_LABEL = {"ethereum": "Ethereum", "bsc": "BSC", "bitcoin": "Bitcoin", "arbitrum": "Arbitrum",
               "polygon": "Polygon", "base": "Base", "avalanche": "Avalanche", "fantom": "Fantom",
               "optimism": "Optimism"}


def to_ts(s):
    return int(datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp())


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_json(url, retries=5):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bridge-limits-probe/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # network or HTTP error
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def llama_prices(coins, ts, cache_file):
    if cache_file.exists():
        cached = json.loads(cache_file.read_text())
        if set(coins) <= set(cached.get("coins", {})) | set(cached.get("missing", [])):
            return cached
    out = {"ts": ts, "coins": {}, "missing": []}
    for i in range(0, len(coins), 40):
        chunk = coins[i:i + 40]
        j = http_json(f"https://coins.llama.fi/prices/historical/{ts}/{','.join(chunk)}?searchWidth=6h")
        out["coins"].update(j.get("coins", {}))
    out["missing"] = [c for c in coins if c not in out["coins"]]
    cache_file.write_text(json.dumps(out, indent=1))
    return out


def evm_rows(leg, w0, w1):
    chain = leg["chain"]
    rpc = Rpc(chain)
    b0 = leg.get("block_from") or rpc.block_at(w0)
    b1 = leg.get("block_to") or rpc.block_at(w1)
    recips = [a.lower() for a in leg["recipients"]]
    rows, meta, tsc = [], {}, {}

    def bts(b):
        if b not in tsc:
            tsc[b] = rpc.block_ts(b)
        return tsc[b]

    if leg.get("erc20", True):
        for rc in recips:
            for lg in rpc.logs(None, [TRANSFER, None, topic_addr(rc)], b0, b1, step=leg.get("log_step", 2000)):
                if len(lg["topics"]) != 3:
                    continue
                blk = int(lg["blockNumber"], 16)
                ts = int(lg["blockTimestamp"], 16) if lg.get("blockTimestamp") else bts(blk)
                tok = lg["address"].lower()
                if leg.get("tokens_only") and tok not in [x.lower() for x in leg["tokens_only"]]:
                    continue
                if tok in [x.lower() for x in leg.get("exclude_tokens", [])]:
                    continue
                sym, dec = erc20_meta(rpc, tok, meta)
                raw = int(lg["data"], 16) if lg["data"] not in ("0x", "") else 0
                rows.append({"chain": chain, "kind": "erc20", "token": tok, "symbol": sym, "decimals": dec,
                             "amount": raw / 10 ** dec, "from": addr_from_topic(lg["topics"][1]).lower(),
                             "to": rc, "block": blk, "ts": ts, "tx": lg["transactionHash"]})
    if leg.get("native", True):
        rt = Rpc(chain + "_trace")
        for x in rt.trace_filter(None, b0, b1, step=leg.get("trace_step", 1000), to_addrs=recips):
            a = x.get("action", {})
            if x.get("type") != "call" or a.get("callType") not in ("call", None):
                continue
            v = int(a.get("value", "0x0"), 16)
            if v == 0:
                continue
            blk = x["blockNumber"]
            rows.append({"chain": chain, "kind": "native", "token": "native",
                         "symbol": leg.get("native_symbol", "ETH"), "decimals": 18, "amount": v / 1e18,
                         "from": (a.get("from") or "").lower(), "to": (a.get("to") or "").lower(),
                         "block": blk, "ts": bts(blk), "tx": x["transactionHash"]})
    return rows, [b0, b1]


def btc_rows(leg, w0, w1):
    rows = []
    for addr in leg["recipients"]:
        seen, last = 0, None
        while True:
            url = f"https://mempool.space/api/address/{addr}/txs/chain" + (f"/{last}" if last else "")
            txs = http_json(url)
            if not txs:
                break
            for tx in txs:
                st = tx.get("status", {})
                ts = st.get("block_time")
                if ts is None:
                    continue
                if w0 <= ts <= w1:
                    sats = sum(o.get("value", 0) for o in tx.get("vout", []) if o.get("scriptpubkey_address") == addr)
                    senders = sorted({(i.get("prevout") or {}).get("scriptpubkey_address") for i in tx.get("vin", [])} - {None})
                    if sats > 0 and addr not in senders:
                        rows.append({"chain": "bitcoin", "kind": "native", "token": "native", "symbol": "BTC",
                                     "decimals": 8, "amount": sats / 1e8, "from": ",".join(senders[:3]),
                                     "to": addr, "block": st.get("block_height"), "ts": ts, "tx": tx["txid"]})
            seen += len(txs)
            oldest = min((t.get("status", {}).get("block_time") or 0) for t in txs)
            last = txs[-1]["txid"]
            if oldest < w0 or len(txs) < 25 or seen > 5000:
                break
            time.sleep(0.5)
    return rows


def coin_id(r):
    if r["token"] == "native":
        return NATIVE_ID[r["chain"]]
    return f"{LLAMA_CHAIN[r['chain']]}:{r['token']}"


def run(tid, t):
    w0, w1 = to_ts(t["window_utc"][0]), to_ts(t["window_utc"][1])
    rows, blocks, errors = [], {}, {}
    for leg in t["legs"]:
        try:
            if leg["chain"] == "bitcoin":
                rows += btc_rows(leg, w0, w1)
            else:
                r, b = evm_rows(leg, w0, w1)
                rows += r
                blocks[leg["chain"]] = b
        except Exception as e:  # a refused endpoint leaves that leg unmeasured, recorded below
            errors[leg["chain"]] = str(e)[:200]
            print("   leg failed:", leg["chain"], str(e)[:120], flush=True)
    only = set(a.lower() for a in t.get("from_only", []))
    excl = set(a.lower() for a in t.get("exclude_from", []))
    for r in rows:
        r["pre_selected"] = (not only or r["from"].lower() in only) and r["from"].lower() not in excl
    if rows:
        ts_first = min(r["ts"] for r in rows if r["pre_selected"]) if any(r["pre_selected"] for r in rows) else min(r["ts"] for r in rows)
        coins = sorted({t.get("price_alias", {}).get(r["token"], coin_id(r)) for r in rows})
        PRICES.mkdir(parents=True, exist_ok=True)
        pr = llama_prices(coins, ts_first, PRICES / f"{tid}.json")
        for r in rows:
            cid = t.get("price_alias", {}).get(r["token"], coin_id(r))
            p = pr["coins"].get(cid, {}).get("price")
            r["price"] = p
            r["usd"] = r["amount"] * p if p is not None else None
    min_usd = t.get("min_usd", 0)
    for r in rows:
        r["selected"] = r["pre_selected"] and (r["usd"] is None or r["usd"] >= min_usd)
    sel = sorted([r for r in rows if r["selected"]], key=lambda r: (r["ts"], str(r["block"])))
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / f"{tid}.json").write_text(json.dumps({"target": tid, "config": t, "blocks": blocks, "rows": rows}, indent=1))
    s = {"target": tid, "event_id": t["event_id"], "leg": t.get("leg"), "chain": ",".join(l["chain"] for l in t["legs"]),
         "selection": "inflows to the recipient addresses" + (" from listed senders" if only else "")
         + (f", min_usd {min_usd}" if min_usd else ""),
         "classified": False, "n_candidate_rows": len(rows), "n_selected_rows": len(sel),
         "legs_not_measured": errors}
    if sel:
        txs = {}
        for r in sel:
            d = txs.setdefault((r["chain"], r["tx"]), {"ts": r["ts"], "usd": 0.0, "usd_missing": 0, "chain": r["chain"]})
            d["ts"] = min(d["ts"], r["ts"])
            if r["usd"] is None:
                d["usd_missing"] += 1
            else:
                d["usd"] += r["usd"]
        tl = sorted(txs.values(), key=lambda d: d["ts"])
        t0, t1 = tl[0]["ts"], tl[-1]["ts"]
        tot = sum(d["usd"] for d in tl)
        by_sym, by_chain = {}, {}
        for r in sel:
            k = f"{r['symbol']}@{r['chain']}"
            by_sym.setdefault(k, [0.0, 0.0])
            by_sym[k][0] += r["amount"]
            by_sym[k][1] += r["usd"] or 0.0
        for d in tl:
            c = by_chain.setdefault(d["chain"], {"n_release_tx": 0, "usd": 0.0, "first": d["ts"], "last": d["ts"]})
            c["n_release_tx"] += 1
            c["usd"] += d["usd"]
            c["first"], c["last"] = min(c["first"], d["ts"]), max(c["last"], d["ts"])
        s.update({
            "first_release_utc": iso(t0), "last_release_utc": iso(t1), "duration_s": t1 - t0,
            "n_release_tx": len(tl), "usd_total": tot,
            "usd_missing_rows": sum(d["usd_missing"] for d in tl),
            "by_symbol": {k: {"amount": round(v[0], 6), "usd": round(v[1], 2)} for k, v in
                          sorted(by_sym.items(), key=lambda kv: -kv[1][1])},
            "by_chain": {k: {"n_release_tx": v["n_release_tx"], "usd": round(v["usd"], 2),
                             "first_utc": iso(v["first"]), "last_utc": iso(v["last"])} for k, v in by_chain.items()},
            "path": [[d["ts"] - t0, round(d["usd"], 2), CHAIN_LABEL.get(d["chain"], d["chain"])] for d in tl],
            "share_within": {str(h): (sum(d["usd"] for d in tl if d["ts"] - t0 <= h) / tot if tot else None)
                             for h in HORIZONS},
        })
    return s


def main():
    cfg = json.loads(CONFIG.read_text())
    want = set(sys.argv[1:])
    summary = json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}
    for tid, t in cfg.items():
        if tid.startswith("_") or t.get("mode") != "inflow" or (want and tid not in want):
            continue
        print("==", tid, flush=True)
        s = run(tid, t)
        # re-read before writing so that concurrent runs on other targets are not overwritten
        summary = json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {}
        summary[tid] = s
        SUMMARY.write_text(json.dumps(summary, indent=1))
        keys = ("first_release_utc", "last_release_utc", "duration_s", "n_release_tx", "usd_total",
                "n_candidate_rows", "n_selected_rows", "share_within", "usd_missing_rows", "by_chain")
        print(json.dumps({k: s.get(k) for k in keys}, indent=None))
        if s.get("by_symbol"):
            print("   ", {k: v for k, v in list(s["by_symbol"].items())[:8]})


if __name__ == "__main__":
    main()
